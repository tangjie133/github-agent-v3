"""
邮件通知系统

功能：
1. 处理失败时通知管理员
2. 排队超时时提供邮件选项
3. HTML 格式邮件模板
"""

import os
import asyncio
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from typing import Optional
from datetime import datetime

from core.logging import get_logger, traced
from core.config import get_config

logger = get_logger(__name__)


class EmailNotifier:
    """
    邮件通知器
    
    使用 SMTP 发送邮件通知管理员
    """
    
    def __init__(self):
        config = get_config()
        
        self.smtp_host = config.notification.smtp_host
        self.smtp_port = config.notification.smtp_port
        self.smtp_user = config.notification.smtp_user
        self.smtp_password = config.notification.smtp_password
        self.admin_email = config.notification.admin_email
        
        self.enabled = config.notification.email_enabled
        
        if not self.enabled:
            logger.warning("email_notifier.disabled",
                         reason="Missing SMTP configuration")
    
    @traced("email.notify_admin")
    async def notify_admin(self,
                          issue_number: int,
                          repo: str,
                          issue_title: str,
                          issue_body: str,
                          failure_reason: str,
                          processed_times: int = 0):
        """
        通知管理员处理问题
        
        Args:
            issue_number: Issue 编号
            repo: 仓库全名
            issue_title: Issue 标题
            issue_body: Issue 内容
            failure_reason: 失败原因
            processed_times: 已尝试次数
        """
        if not self.enabled:
            logger.debug("email.notify_skipped", reason="not_enabled")
            return
        
        subject = f"[GitHub Agent] 需要人工处理: {repo}#{issue_number}"
        
        # HTML 邮件正文
        body = f"""
<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .header {{ background: #f44336; color: white; padding: 20px; }}
        .content {{ padding: 20px; }}
        .info-box {{ background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 5px; }}
        .error-box {{ background: #ffebee; padding: 15px; border-left: 4px solid #f44336; margin: 10px 0; }}
        pre {{ background: #263238; color: #aed581; padding: 15px; overflow-x: auto; border-radius: 5px; }}
        .button {{ display: inline-block; background: #4CAF50; color: white; padding: 10px 20px; 
                  text-decoration: none; border-radius: 5px; margin: 10px 0; }}
        .footer {{ color: #666; font-size: 12px; margin-top: 30px; padding-top: 20px; border-top: 1px solid #ddd; }}
    </style>
</head>
<body>
    <div class="header">
        <h2>🤖 GitHub Agent 无法自动处理的问题</h2>
    </div>
    
    <div class="content">
        <h3>问题信息</h3>
        <div class="info-box">
            <p><strong>仓库:</strong> {repo}</p>
            <p><strong>Issue:</strong> #{issue_number}</p>
            <p><strong>标题:</strong> {issue_title}</p>
            <p><strong>尝试次数:</strong> {processed_times}</p>
        </div>
        
        <h3>失败原因</h3>
        <div class="error-box">
            <pre>{failure_reason}</pre>
        </div>
        
        <h3>Issue 内容</h3>
        <pre>{issue_body[:2000]}{'...' if len(issue_body) > 2000 else ''}</pre>
        
        <h3>操作</h3>
        <p>
            <a href="https://github.com/{repo}/issues/{issue_number}" class="button">
                查看 Issue
            </a>
        </p>
    </div>
    
    <div class="footer">
        <p>此邮件由 GitHub Agent V3 自动发送于 {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</p>
        <p>如需调整通知设置，请修改配置文件的 notification 部分</p>
    </div>
</body>
</html>
"""
        
        try:
            await self._send_email(subject, body, is_html=True)
            logger.info("email.sent_to_admin",
                       repo=repo,
                       issue=issue_number,
                       admin=self.admin_email)
        except Exception as e:
            logger.error("email.send_failed",
                        error_type=type(e).__name__,
                        error=str(e))
    
    async def send_queue_notification(self,
                                     owner: str,
                                     repo: str,
                                     issue_number: int,
                                     message: str,
                                     github_client=None):
        """
        发送排队提示到 Issue 评论
        
        如果配置了邮件，同时提供邮件选项
        """
        full_message = message
        
        # 如果邮件可用，添加邮件选项
        if self.enabled and self.admin_email:
            mailto_link = (
                f"mailto:{self.admin_email}"
                f"?subject=[GitHub Agent] 请协助处理 {repo}#{issue_number}"
                f"&body=请协助处理此问题..."
            )
            
            full_message += f"\n\n---\n"
            full_message += f"**如需紧急处理，请 [发送邮件给管理员]({mailto_link})**\n"
            full_message += f"或直接回复此 Issue，管理员会尽快查看。"
        
        # 如果提供了 GitHub 客户端，直接发送评论
        if github_client:
            try:
                github_client.create_issue_comment(
                    owner, repo, issue_number, full_message
                )
                logger.info("queue.comment_sent",
                           repo=repo,
                           issue=issue_number)
            except Exception as e:
                logger.error("queue.comment_failed",
                            error=str(e))
    
    async def _send_email(self, subject: str, body: str, is_html: bool = True):
        """发送邮件"""
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = self.smtp_user
        msg['To'] = self.admin_email
        
        if is_html:
            msg.attach(MIMEText(body, 'html', 'utf-8'))
        else:
            msg.attach(MIMEText(body, 'plain', 'utf-8'))
        
        # 在线程池中执行同步 SMTP 操作
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(
            None, self._send_smtp_sync, msg
        )
    
    def _send_smtp_sync(self, msg: MIMEMultipart):
        """同步发送 SMTP"""
        with smtplib.SMTP(self.smtp_host, self.smtp_port) as server:
            server.starttls()
            server.login(self.smtp_user, self.smtp_password)
            server.send_message(msg)


# 全局单例
_email_notifier: Optional[EmailNotifier] = None


def get_email_notifier() -> EmailNotifier:
    """获取 EmailNotifier 单例"""
    global _email_notifier
    if _email_notifier is None:
        _email_notifier = EmailNotifier()
    return _email_notifier