"""
邮件通知器测试
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import Mock, AsyncMock, patch, MagicMock
import asyncio

from core.notification.email import EmailNotifier, get_email_notifier


class TestEmailNotifier:
    """邮件通知器单元测试"""
    
    @pytest.fixture
    def mock_config(self):
        """模拟配置"""
        config = Mock()
        config.notification.smtp_host = 'smtp.gmail.com'
        config.notification.smtp_port = 587
        config.notification.smtp_user = 'test@example.com'
        config.notification.smtp_password = 'testpassword'
        config.notification.admin_email = 'admin@example.com'
        config.notification.notify_admin_on_failure = True
        config.notification.email_enabled = True
        return config
    
    def test_init(self, mock_config):
        """测试初始化"""
        with patch('core.notification.email.get_config', return_value=mock_config):
            notifier = EmailNotifier()
            assert notifier.enabled is True
            assert notifier.smtp_host == mock_config.notification.smtp_host
            assert notifier.admin_email == mock_config.notification.admin_email
    
    def test_init_disabled(self):
        """测试禁用状态"""
        config = Mock()
        config.notification.smtp_user = None
        config.notification.smtp_password = None
        config.notification.admin_email = None
        config.notification.email_enabled = False
        
        with patch('core.notification.email.get_config', return_value=config):
            notifier = EmailNotifier()
            assert notifier.enabled is False
    
    @pytest.mark.asyncio
    async def test_notify_admin_success(self, mock_config):
        """测试通知管理员成功"""
        with patch('core.notification.email.get_config', return_value=mock_config):
            notifier = EmailNotifier()
            with patch.object(notifier, '_send_email', new_callable=AsyncMock) as mock_send:
                await notifier.notify_admin(
                    issue_number=123,
                    repo="owner/repo",
                    issue_title="Test Issue",
                    issue_body="This is a test issue",
                    failure_reason="Test failure reason",
                    processed_times=2
                )
                
                mock_send.assert_called_once()
                call_args = mock_send.call_args
                assert "需要人工处理" in call_args[0][0]
                assert "owner/repo" in call_args[0][1]
    
    @pytest.mark.asyncio
    async def test_notify_admin_disabled(self):
        """测试禁用时跳过"""
        config = Mock()
        config.notification.email_enabled = False
        
        with patch('core.notification.email.get_config', return_value=config):
            notifier = EmailNotifier()
            
            with patch.object(notifier, '_send_email', new_callable=AsyncMock) as mock_send:
                await notifier.notify_admin(
                    issue_number=123,
                    repo="owner/repo",
                    issue_title="Test Issue",
                    issue_body="body",
                    failure_reason="reason"
                )
                
                mock_send.assert_not_called()
    
    @pytest.mark.asyncio
    async def test_send_email(self, mock_config):
        """测试发送邮件"""
        mock_smtp = MagicMock()
        mock_smtp.__enter__ = Mock(return_value=mock_smtp)
        mock_smtp.__exit__ = Mock(return_value=False)
        
        with patch('core.notification.email.get_config', return_value=mock_config):
            notifier = EmailNotifier()
            with patch('smtplib.SMTP', return_value=mock_smtp):
                await notifier._send_email("Test Subject", "Test Body", is_html=False)
                
                # 验证 SMTP 调用
                mock_smtp.starttls.assert_called_once()
                mock_smtp.login.assert_called_once_with(
                    notifier.smtp_user, notifier.smtp_password
                )
                mock_smtp.send_message.assert_called_once()
    
    @pytest.mark.asyncio
    async def test_send_queue_notification_with_email(self, mock_config):
        """测试排队通知带邮件选项"""
        mock_github = Mock()
        mock_github.create_issue_comment = Mock()
        
        with patch('core.notification.email.get_config', return_value=mock_config):
            notifier = EmailNotifier()
            await notifier.send_queue_notification(
                owner="owner",
                repo="repo",
                issue_number=123,
                message="Your issue is in queue",
                github_client=mock_github
            )
            
            # 验证 GitHub 评论被调用
            mock_github.create_issue_comment.assert_called_once()
            call_args = mock_github.create_issue_comment.call_args
            assert "owner" == call_args[0][0]
            assert "repo" == call_args[0][1]
            assert 123 == call_args[0][2]
            
            # 验证包含邮件链接
            comment_body = call_args[0][3]
            assert "发送邮件给管理员" in comment_body
            assert "mailto:" in comment_body
    
    @pytest.mark.asyncio
    async def test_send_queue_notification_without_github_client(self):
        """测试无 GitHub 客户端时不发送"""
        config = Mock()
        config.notification.email_enabled = False
        
        with patch('core.notification.email.get_config', return_value=config):
            notifier = EmailNotifier()
            # 应该不抛出异常
            await notifier.send_queue_notification(
                owner="owner",
                repo="repo",
                issue_number=123,
                message="Test message",
                github_client=None
            )
    
    @pytest.mark.asyncio
    async def test_send_queue_notification_github_error(self):
        """测试 GitHub 错误处理"""
        config = Mock()
        config.notification.email_enabled = False
        
        with patch('core.notification.email.get_config', return_value=config):
            notifier = EmailNotifier()
            mock_github = Mock()
            mock_github.create_issue_comment = Mock(side_effect=Exception("API Error"))
            
            # 应该不抛出异常
            await notifier.send_queue_notification(
                owner="owner",
                repo="repo",
                issue_number=123,
                message="Test",
                github_client=mock_github
            )


class TestEmailNotifierSingleton:
    """邮件通知器单例测试"""
    
    def test_get_email_notifier_singleton(self):
        """测试单例模式"""
        config = Mock()
        config.notification.smtp_host = 'smtp.test.com'
        config.notification.smtp_port = 587
        config.notification.smtp_user = None
        config.notification.smtp_password = None
        config.notification.admin_email = None
        config.notification.email_enabled = False
        
        with patch('core.notification.email.get_config', return_value=config):
            notifier1 = get_email_notifier()
            notifier2 = get_email_notifier()
            
            assert notifier1 is notifier2
    
    @pytest.mark.asyncio
    async def test_email_content_format(self):
        """测试邮件内容格式"""
        config = Mock()
        config.notification.smtp_host = 'smtp.gmail.com'
        config.notification.smtp_port = 587
        config.notification.smtp_user = 'test@example.com'
        config.notification.smtp_password = 'password'
        config.notification.admin_email = 'admin@example.com'
        config.notification.email_enabled = True
        
        with patch('core.notification.email.get_config', return_value=config):
            notifier = EmailNotifier()
            
            with patch.object(notifier, '_send_email', new_callable=AsyncMock) as mock_send:
                await notifier.notify_admin(
                    issue_number=42,
                    repo="myorg/myrepo",
                    issue_title="Bug in authentication",
                    issue_body="Users cannot login with OAuth",
                    failure_reason="API rate limit exceeded",
                    processed_times=3
                )
                
                args = mock_send.call_args[0]
                subject = args[0]
                body = args[1]
                is_html = args[2] if len(args) > 2 else True
                
                # 验证主题
                assert "需要人工处理" in subject
                assert "myorg/myrepo" in subject
                assert "#42" in subject
                
                # 验证 HTML 内容
                assert is_html is True
                assert "<html>" in body
                assert "Bug in authentication" in body
                assert "API rate limit exceeded" in body
                assert "GitHub Agent V3" in body
                assert "3" in body  # processed_times
