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


def verify_signature(payload: bytes, signature: str, secret: str) -> bool:
    """验证 GitHub Webhook 签名"""
    if not signature or not secret:
        return False
    
    # GitHub 签名格式: sha256=<hex>
    expected = hmac.new(
        secret.encode(),
        payload,
        hashlib.sha256
    ).hexdigest()
    
    return hmac.compare_digest(f"sha256={expected}", signature)


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
    判断是否应该处理此 Issue
    
    规则：
    - 只处理 'opened' 和 'edited' 动作
    - 忽略 Bot 创建的 Issue
    """
    if payload.action not in ["opened", "edited"]:
        return False
    
    if is_bot(payload.payload):
        logger.info("webhook.ignore_bot_issue",
                   issue=payload.issue.get("number"))
        return False
    
    return True


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
    
    # 签名验证
    if not verify_signature(body, x_hub_signature_256, 
                           config.github.webhook_secret or ""):
        logger.error("webhook.invalid_signature",
                    client_ip=client_ip,
                    event=x_github_event)
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
               event=x_github_event,
               action=payload.action,
               delivery=x_github_delivery)
    
    # 路由处理
    try:
        if payload.is_issue and should_process_issue(payload):
            await handle_issue_event(payload)
        
        elif payload.is_issue_comment and should_process_comment(payload):
            await handle_comment_event(payload)
        
        else:
            logger.debug("webhook.ignored",
                        event=x_github_event,
                        action=payload.action)
    
    except Exception as e:
        logger.error("webhook.handle_error",
                    event=x_github_event,
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
        status=QueueStatus.PENDING
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
    
    检查是否是确认/拒绝指令，如果是则处理
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
               user=username)
    
    # 检查是否是确认指令
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
        logger.debug("webhook.not_confirmation_comment",
                    owner=owner,
                    repo=repo_name,
                    issue=issue_number)


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
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


if __name__ == "__main__":
    asyncio.run(start_server())