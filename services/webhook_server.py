"""
Webhook 服务器

接收 GitHub Webhook 事件并路由到处理器
"""

import os
import hmac
import hashlib
import asyncio
import time
from typing import Dict, Any, Optional, List
from dataclasses import dataclass

from fastapi import FastAPI, Request, HTTPException, Header
from fastapi.responses import JSONResponse
import uvicorn

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.logging import get_logger, traced
from core.config import get_config
from core.queue.manager import get_queue_manager, QueueEntry, QueueStatus, Priority
from services.processor import get_issue_processor
from core.confirmation import get_confirmation_manager

logger = get_logger(__name__)

app = FastAPI(title="GitHub Agent Webhook Server")

# 限流存储
_request_times: Dict[str, List[float]] = {}


@dataclass
class WebhookPayload:
    """Webhook 数据封装"""
    event_type: str
    action: str
    payload: Dict[str, Any]
    
    @property
    def is_issue(self) -> bool:
        return self.event_type == "issues"
    
    @property
    def is_issue_comment(self) -> bool:
        return self.event_type == "issue_comment"
    
    @property
    def repository(self) -> Dict[str, Any]:
        return self.payload.get("repository", {})
    
    @property
    def issue(self) -> Dict[str, Any]:
        return self.payload.get("issue", {})
    
    @property
    def comment(self) -> Dict[str, Any]:
        return self.payload.get("comment", {})
    
    @property
    def sender(self) -> Dict[str, Any]:
        return self.payload.get("sender", {})
    
    @property
    def installation(self) -> Dict[str, Any]:
        return self.payload.get("installation", {})
    
    @property
    def installation_id(self) -> Optional[int]:
        return self.installation.get("id")


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """验证 GitHub Webhook 签名"""
    # 开发模式：跳过验证（设置 WEBHOOK_SKIP_VERIFY=1 ）
    if os.getenv('WEBHOOK_SKIP_VERIFY') == '1':
        logger.warning("webhook.signature_skipped", mode="development")
        return True
    
    if not signature:
        logger.warning("webhook.signature_missing")
        return False
    
    if not secret:
        logger.warning("webhook.secret_not_configured")
        return False
    
    # 调试：记录签名前几个字符（不记录完整签名）
    logger.debug("webhook.signature_debug",
                signature_prefix=signature[:20] if signature else "none",
                secret_length=len(secret),
                payload_length=len(payload))
    
    # GitHub 签名格式: sha256=<hex>
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    expected_full = f"sha256={expected}"
    is_valid = hmac.compare_digest(expected_full, signature)
    
    if not is_valid:
        logger.warning("webhook.signature_mismatch",
                      expected_prefix=expected_full[:20],
                      received_prefix=signature[:20])
    
    return is_valid


def check_rate_limit(client_ip: str, max_requests: int = 100, 
                    window_seconds: int = 60) -> bool:
    """检查限流"""
    now = time.time()
    
    # 清理旧记录
    _request_times[client_ip] = [
        t for t in _request_times.get(client_ip, [])
        if now - t < window_seconds
    ]
    
    # 检查限流
    if len(_request_times[client_ip]) >= max_requests:
        return False
    
    _request_times[client_ip].append(now)
    return True


def is_bot(payload: Dict[str, Any]) -> bool:
    """检查是否由 Bot 触发"""
    sender_type = payload.get("sender", {}).get("type", "")
    sender_login = payload.get("sender", {}).get("login", "")
    
    if sender_type == "Bot":
        return True
    if "[bot]" in sender_login:
        return True
    if sender_login.endswith("-bot"):
        return True
    
    return False


def should_process_issue(payload: WebhookPayload) -> bool:
    """
    判断是否应该自动处理此 Issue
    
    规则（方案 B - @agent 触发模式）：
    - 不自动处理 Issue 创建/编辑
    - 只处理 Bot 创建的 Issue（如果需要）
    - 用户需要通过 @agent 评论来触发
    
    如需改为自动模式，修改配置 processing.confirm_mode = auto
    """
    config = get_config()
    
    # 如果是 AUTO 模式，自动处理
    if config.processing.confirm_mode == "auto":
        if payload.action not in ["opened", "edited"]:
            return False
        if is_bot(payload.payload):
            logger.info("webhook.ignore_bot_issue",
                       issue=payload.issue.get("number"))
            return False
        return True
    
    # SMART/MANUAL 模式（@agent 触发）
    # Issue 创建时不自动处理，等待 @agent 评论触发
    return False


def should_process_comment(payload: WebhookPayload) -> bool:
    """
    判断是否应该处理此评论
    
    规则：
    - 只处理 'created' 动作
    - 忽略 Bot 评论
    - 检查是否是确认/拒绝指令
    """
    if payload.action != "created":
        return False
    
    if is_bot(payload.payload):
        logger.info("webhook.ignore_bot_comment")
        return False
    
    return True


@app.post("/webhook")
@app.post("/webhook/github")
async def github_webhook(
    request: Request,
    x_hub_signature_256: Optional[str] = Header(None),
    x_github_event: str = Header(""),
    x_github_delivery: str = Header("")
):
    """
    GitHub Webhook 入口
    """
    config = get_config()
    client_ip = request.client.host if request.client else "unknown"
    
    # 限流检查
    if not check_rate_limit(client_ip):
        logger.warning("webhook.rate_limited", client_ip=client_ip)
        raise HTTPException(429, "Rate limit exceeded")
    
    # 读取 payload
    body = await request.body()
    
    # 签名验证 - 优先使用环境变量 GITHUB_WEBHOOK_SECRET，其次使用配置
    webhook_secret = os.getenv("GITHUB_WEBHOOK_SECRET") or config.github.webhook_secret or ""
    
    if not verify_signature(body, x_hub_signature_256, webhook_secret):
        logger.error("webhook.invalid_signature",
                    client_ip=client_ip,
                    github_event=x_github_event,
                    secret_configured=bool(webhook_secret))
        raise HTTPException(401, "Invalid signature")
    
    # 解析 payload
    try:
        payload_data = await request.json()
    except Exception as e:
        logger.error("webhook.parse_error", error=str(e))
        raise HTTPException(400, "Invalid JSON")
    
    payload = WebhookPayload(
        event_type=x_github_event,
        action=payload_data.get("action", ""),
        payload=payload_data
    )
    
    logger.info("webhook.received",
               github_event=x_github_event,
               action=payload.action,
               delivery=x_github_delivery,
               is_issue=payload.is_issue,
               is_comment=payload.is_issue_comment,
               repo=payload.repository.get("full_name"))
    
    # 路由处理
    try:
        if payload.is_issue:
            config = get_config()
            should_process = should_process_issue(payload)
            
            logger.debug("webhook.checking_issue",
                        action=payload.action,
                        confirm_mode=config.processing.confirm_mode,
                        should_process=should_process)
            
            if should_process:
                await handle_issue_event(payload)
            else:
                if config.processing.confirm_mode in ["manual", "smart"]:
                    logger.info("webhook.issue_skipped_use_agent",
                               action=payload.action,
                               message="Use @agent comment to trigger")
                else:
                    logger.info("webhook.issue_ignored",
                               action=payload.action,
                               reason="filters_not_met")
        
        elif payload.is_issue_comment:
            logger.debug("webhook.checking_comment",
                        should_process=should_process_comment(payload))
            if should_process_comment(payload):
                await handle_comment_event(payload)
            else:
                logger.info("webhook.comment_ignored",
                           reason="filters_not_met")
        
        else:
            logger.debug("webhook.ignored",
                        github_event=x_github_event,
                        action=payload.action,
                        reason="unsupported_event_type")
    
    except Exception as e:
        logger.error("webhook.handle_error",
                    github_event=x_github_event,
                    error=str(e))
        # 返回 200 避免 GitHub 重试
    
    return {"status": "ok"}


@traced("webhook.handle_issue")
async def handle_issue_event(payload: WebhookPayload):
    """
    处理 Issue 事件
    
    将 Issue 添加到处理队列
    """
    repo = payload.repository
    issue = payload.issue
    
    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    issue_number = issue.get("number", 0)
    title = issue.get("title", "")
    body = issue.get("body", "")
    
    logger.info("webhook.enqueue_issue",
               owner=owner,
               repo=repo_name,
               issue=issue_number)
    
    # 创建队列任务
    queue_mgr = await get_queue_manager()
    
    entry = QueueEntry(
        issue_id=f"{owner}/{repo_name}#{issue_number}",
        owner=owner,
        repo=repo_name,
        issue_number=issue_number,
        title=title,
        body=body,
        priority=Priority.NORMAL.value,
        event_type="issues",
        status=QueueStatus.PENDING,
        installation_id=payload.installation_id
    )
    
    await queue_mgr.enqueue(entry)
    
    logger.info("webhook.issue_enqueued",
               owner=owner,
               repo=repo_name,
               issue=issue_number)


@traced("webhook.handle_comment")
async def handle_comment_event(payload: WebhookPayload):
    """
    处理 Issue 评论事件
    
    支持：
    1. @agent 触发修复
    2. confirm/cancel 确认指令
    """
    repo = payload.repository
    issue = payload.issue
    comment = payload.comment
    sender = payload.sender
    
    owner = repo.get("owner", {}).get("login", "")
    repo_name = repo.get("name", "")
    issue_number = issue.get("number", 0)
    comment_body = comment.get("body", "")
    username = sender.get("login", "")
    
    logger.info("webhook.comment_received",
               owner=owner,
               repo=repo_name,
               issue=issue_number,
               user=username,
               comment_preview=comment_body[:50] if comment_body else "")
    
    # 1. 检查是否是 @agent 触发
    if is_agent_mentioned(comment_body):
        logger.info("webhook.agent_mentioned",
                   owner=owner,
                   repo=repo_name,
                   issue=issue_number)
        
        # 触发 Issue 处理
        await handle_agent_trigger(
            owner, repo_name, issue_number,
            issue.get("title", ""),
            issue.get("body", ""),
            payload.installation_id
        )
        return
    
    # 2. 检查是否是确认指令
    processor = await get_issue_processor()
    
    result = await processor.handle_comment(
        owner=owner,
        repo=repo_name,
        issue_number=issue_number,
        comment_body=comment_body,
        username=username
    )
    
    if result:
        logger.info("webhook.confirmation_handled",
                   owner=owner,
                   repo=repo_name,
                   issue=issue_number,
                   status=result.value)
    else:
        logger.debug("webhook.not_command_comment",
                    owner=owner,
                    repo=repo_name,
                    issue=issue_number)


def is_agent_mentioned(comment_body: str) -> bool:
    """检查评论是否提到了 @agent"""
    if not comment_body:
        return False
    
    # 支持的触发词
    triggers = [
        "@agent",
        "@github-agent",
        "@bot",
    ]
    
    comment_lower = comment_body.lower()
    return any(trigger in comment_lower for trigger in triggers)


async def handle_agent_trigger(owner: str, repo: str, issue_number: int,
                               issue_title: str, issue_body: str,
                               installation_id: Optional[int] = None):
    """处理 @agent 触发"""
    logger.info("webhook.agent_trigger_processing",
               owner=owner,
               repo=repo,
               issue=issue_number)
    
    # 1. 意图识别 - 判断是否为纯问答
    # 提取触发指令（去掉@agent）
    instruction = issue_body.lower()
    
    # 定义纯问答关键词（不需要代码处理）
    QNA_KEYWORDS = [
        "你能干什么", "你会做什么", "你有什么功能", "功能介绍",
        "你是谁", "你是什么", "介绍一下自己",
        "帮助", "help", "如何使用", "怎么用"
    ]
    
    # 定义代码修复关键词（需要入队处理）
    CODE_KEYWORDS = [
        "修复", "修改", "改成", "解决", "fix", "bug", "error",
        "报错", "错误", "异常", "修改代码", "改一下"
    ]
    
    # 判断意图
    is_qna = any(kw in instruction for kw in QNA_KEYWORDS)
    is_code = any(kw in instruction for kw in CODE_KEYWORDS)
    
    # 2. 纯问答直接回答，不入队
    if is_qna and not is_code:
        logger.info("webhook.direct_qna_response",
                   owner=owner, repo=repo, issue=issue_number)
        
        try:
            from core.github_api import get_github_client
            github = get_github_client()
            github.set_installation_id(installation_id)
            
            # 直接回答，不发送"处理中"消息
            answer = """👋 你好！我是 GitHub Agent，一个智能代码助手。

**我能帮你：**
1. 🐛 **修复 Bug** - 分析 Issue 中的错误并自动生成修复代码
2. ✨ **代码修改** - 根据你的需求修改代码逻辑
3. 📝 **代码审查** - 检查代码潜在问题
4. 💡 **技术咨询** - 回答编程相关问题

**使用方法：**
- `@agent 修复这个问题` - 自动分析并修复
- `@agent 把XX改成YY` - 按需求修改代码
- `@agent 分析一下` - 代码审查

需要我帮你处理什么代码问题吗？"""
            
            await github.create_issue_comment(owner, repo, issue_number, answer)
            
            logger.info("webhook.direct_qna_sent",
                       owner=owner, repo=repo, issue=issue_number)
            return  # 直接返回，不入队
            
        except Exception as e:
            logger.error("webhook.direct_qna_failed",
                        owner=owner, repo=repo, issue=issue_number,
                        error=str(e))
            return
    
    # 3. 代码相关问题 - 入队处理
    try:
        from core.github_api import get_github_client
        github = get_github_client()
        github.set_installation_id(installation_id)
        
        # 发送处理中通知
        await github.create_issue_comment(
            owner, repo, issue_number,
            "👋 收到！我正在分析这个问题，请稍候..."
        )
        logger.info("webhook.agent_trigger_ack_sent",
                   owner=owner, repo=repo, issue=issue_number)
    except Exception as e:
        logger.warning("webhook.agent_trigger_ack_failed",
                      owner=owner, repo=repo, issue=issue_number,
                      error=str(e))
    
    try:
        # 添加到处理队列
        queue_mgr = await get_queue_manager()
        
        position = await queue_mgr.enqueue(
            issue_id=f"{owner}/{repo}#{issue_number}",
            repo=repo,
            issue_number=issue_number,
            event_type="agent_trigger",
            priority=Priority.NORMAL.value,
            owner=owner,
            title=issue_title,
            body=issue_body,
            installation_id=installation_id
        )
        
        logger.info("webhook.agent_trigger_enqueued",
                   owner=owner,
                   repo=repo,
                   issue=issue_number,
                   queue_position=position.position)
        
    except Exception as e:
        logger.error("webhook.agent_trigger_failed",
                    owner=owner,
                    repo=repo,
                    issue=issue_number,
                    error=str(e),
                    exc_info=True)


@app.get("/health")
async def health_check():
    """健康检查"""
    return {
        "status": "healthy",
        "timestamp": time.time()
    }


async def start_server(host: str = "0.0.0.0", port: int = 8000):
    """启动服务器"""
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        timeout_graceful_shutdown=5  # 5秒优雅关闭超时
    )
    server = uvicorn.Server(config)
    
    # 覆盖默认信号处理，让主进程管理信号
    server.install_signal_handlers = lambda: None
    
    await server.serve()


if __name__ == "__main__":
    asyncio.run(start_server())