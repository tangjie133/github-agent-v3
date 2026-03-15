"""
人工确认机制

功能：
- 开关控制 (auto/manual)
- 创建 Preview PR (Draft)
- 在 Issue 中等待确认
- 超时自动处理
- 记录用户决策
"""

import asyncio
import re
from enum import Enum
from typing import Optional, Dict, Any, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from core.utils import utc_now

from core.logging import get_logger, traced
from core.config import get_config
from core.i18n import t_detect

logger = get_logger(__name__)


class ConfirmMode(Enum):
    """确认模式"""
    AUTO = "auto"       # 自动确认
    MANUAL = "manual"   # 人工确认（默认）


class ConfirmStatus(Enum):
    """确认状态"""
    PENDING = "pending"     # 等待确认
    CONFIRMED = "confirmed" # 已确认
    REJECTED = "rejected"   # 已拒绝
    TIMEOUT = "timeout"     # 超时
    AUTO = "auto"           # 自动通过


@dataclass
class ConfirmationRecord:
    """确认记录"""
    issue_number: int
    repo: str
    preview_pr_number: Optional[int] = None
    status: ConfirmStatus = ConfirmStatus.PENDING
    created_at: datetime = field(default_factory=utc_now)
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[str] = None  # 用户名或 "system"
    decision_comment_id: Optional[int] = None
    files_changed: list = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def is_expired(self, timeout_hours: int) -> bool:
        """检查是否超时"""
        if self.status != ConfirmStatus.PENDING:
            return False
        deadline = self.created_at + timedelta(hours=timeout_hours)
        return utc_now() > deadline
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典"""
        return {
            "issue_number": self.issue_number,
            "repo": self.repo,
            "preview_pr_number": self.preview_pr_number,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolved_by": self.resolved_by,
            "files_changed": self.files_changed,
        }


class ConfirmationManager:
    """
    确认管理器
    
    管理所有待确认的修复方案
    """
    
    def __init__(self):
        config = get_config()
        self.mode = ConfirmMode(config.processing.confirm_mode)
        self.timeout_hours = getattr(config.processing, 'confirm_timeout_hours', 168)  # 默认7天
        self.auto_threshold = config.processing.auto_confirm_threshold
        
        # 内存中的确认记录（生产环境应使用持久化存储）
        self._records: Dict[str, ConfirmationRecord] = {}
        
        # 回调函数
        self._on_confirm: Optional[Callable] = None
        self._on_reject: Optional[Callable] = None
        self._on_timeout: Optional[Callable] = None
        
        logger.info("confirmation.manager_init",
                   mode=self.mode.value,
                   timeout_hours=self.timeout_hours)
    
    def _make_key(self, repo: str, issue_number: int) -> str:
        """生成记录键"""
        return f"{repo}#{issue_number}"
    
    @traced("confirmation.create")
    async def create_confirmation(self,
                                  repo: str,
                                  issue_number: int,
                                  preview_pr_number: int,
                                  files_changed: list,
                                  issue_body: str = "",
                                  confidence: float = 0.0) -> ConfirmationRecord:
        """
        创建确认请求
        
        Args:
            repo: 仓库全名
            issue_number: Issue 编号
            preview_pr_number: 预览 PR 编号
            files_changed: 修改的文件列表
            issue_body: Issue 内容（用于语言检测）
            confidence: LLM 置信度 (0-1)
        
        Returns:
            确认记录
        """
        # 如果是 auto 模式且置信度足够高，直接通过
        if self.mode == ConfirmMode.AUTO and confidence >= self.auto_threshold:
            logger.info("confirmation.auto_approved",
                       repo=repo,
                       issue=issue_number,
                       confidence=confidence)
            
            record = ConfirmationRecord(
                issue_number=issue_number,
                repo=repo,
                preview_pr_number=preview_pr_number,
                status=ConfirmStatus.AUTO,
                files_changed=files_changed,
                resolved_at=utc_now(),
                resolved_by="system(auto)"
            )
            
            key = self._make_key(repo, issue_number)
            self._records[key] = record
            
            return record
        
        # 创建待确认记录
        record = ConfirmationRecord(
            issue_number=issue_number,
            repo=repo,
            preview_pr_number=preview_pr_number,
            status=ConfirmStatus.PENDING,
            files_changed=files_changed
        )
        
        key = self._make_key(repo, issue_number)
        self._records[key] = record
        
        logger.info("confirmation.created",
                   repo=repo,
                   issue=issue_number,
                   preview_pr=preview_pr_number,
                   mode=self.mode.value)
        
        return record
    
    def get_confirmation_message(self, record: ConfirmationRecord, 
                                 issue_body: str = "") -> str:
        """
        生成确认请求评论内容
        """
        lang = self._detect_language(issue_body)
        
        lines = [
            f"## {t_detect('fix_preview_title', issue_body)}",
            "",
            t_detect('fix_generated', issue_body, file_count=len(record.files_changed)),
            "",
            t_detect('preview_pr_created', issue_body, pr_number=record.preview_pr_number),
            "",
            f"**{t_detect('files_modified', issue_body)}**",
        ]
        
        for f in record.files_changed:
            lines.append(f"- `{f}`")
        
        lines.extend([
            "",
            "---",
            "",
            t_detect('confirm_prompt', issue_body),
            "",
            f"{t_detect('confirm_button', issue_body)} | {t_detect('reject_button', issue_body)} | {t_detect('modify_button', issue_body)}",
            "",
            f"*{t_detect('timeout_notice', issue_body, hours=self.timeout_hours)}*",
        ])
        
        return "\n".join(lines)
    
    async def parse_user_response(self, comment_body: str) -> Optional[ConfirmStatus]:
        """
        解析用户评论，判断是否确认/拒绝
        
        支持的指令：
        - 确认: "确认", "approve", "confirm", "apply", "LGTM"
        - 拒绝: "拒绝", "reject", "cancel", "关闭", "close"
        """
        comment_lower = comment_body.lower()
        
        # 确认关键词
        confirm_patterns = [
            r'\b(confirm|approve|apply|lgtm)\b',
            r'确认|同意|应用|通过',
        ]
        
        # 拒绝关键词  
        reject_patterns = [
            r'\b(reject|cancel|close|deny)\b',
            r'拒绝|取消|关闭|不通过',
        ]
        
        for pattern in confirm_patterns:
            if re.search(pattern, comment_lower):
                return ConfirmStatus.CONFIRMED
        
        for pattern in reject_patterns:
            if re.search(pattern, comment_lower):
                return ConfirmStatus.REJECTED
        
        return None
    
    async def handle_user_response(self,
                                   repo: str,
                                   issue_number: int,
                                   comment_body: str,
                                   username: str) -> Optional[ConfirmStatus]:
        """
        处理用户响应
        
        Returns:
            新的状态，如果不是有效响应则返回 None
        """
        key = self._make_key(repo, issue_number)
        record = self._records.get(key)
        
        if not record:
            logger.warning("confirmation.record_not_found",
                          repo=repo, issue=issue_number)
            return None
        
        if record.status != ConfirmStatus.PENDING:
            logger.debug("confirmation.already_resolved",
                        repo=repo, issue=issue_number, status=record.status.value)
            return None
        
        decision = await self.parse_user_response(comment_body)
        if not decision:
            return None
        
        # 更新记录
        record.status = decision
        record.resolved_at = utc_now()
        record.resolved_by = username
        
        logger.info("confirmation.resolved",
                   repo=repo,
                   issue=issue_number,
                   status=decision.value,
                   by=username)
        
        # 触发回调
        if decision == ConfirmStatus.CONFIRMED and self._on_confirm:
            await self._on_confirm(record)
        elif decision == ConfirmStatus.REJECTED and self._on_reject:
            await self._on_reject(record)
        
        return decision
    
    async def check_timeouts(self):
        """
        检查并处理超时的确认请求
        
        应定期调用（如每小时）
        """
        expired = []
        
        for key, record in self._records.items():
            if record.status == ConfirmStatus.PENDING and record.is_expired(self.timeout_hours):
                expired.append(record)
        
        for record in expired:
            record.status = ConfirmStatus.TIMEOUT
            record.resolved_at = utc_now()
            record.resolved_by = "system(timeout)"
            
            logger.info("confirmation.timeout",
                       repo=record.repo,
                       issue=record.issue_number)
            
            if self._on_timeout:
                await self._on_timeout(record)
        
        return expired
    
    def get_record(self, repo: str, issue_number: int) -> Optional[ConfirmationRecord]:
        """获取确认记录"""
        key = self._make_key(repo, issue_number)
        return self._records.get(key)
    
    def set_callbacks(self,
                     on_confirm: Optional[Callable] = None,
                     on_reject: Optional[Callable] = None,
                     on_timeout: Optional[Callable] = None):
        """
        设置回调函数
        
        Args:
            on_confirm: 确认时的回调 (record) -> None
            on_reject: 拒绝时的回调 (record) -> None
            on_timeout: 超时时的回调 (record) -> None
        """
        self._on_confirm = on_confirm
        self._on_reject = on_reject
        self._on_timeout = on_timeout
    
    def _detect_language(self, text: str) -> str:
        """检测语言"""
        try:
            from core.i18n import get_i18n
            return get_i18n().detect_language(text)
        except Exception:
            return "en"
    
    def is_auto_mode(self) -> bool:
        """是否为自动模式"""
        return self.mode == ConfirmMode.AUTO
    
    def get_stats(self) -> Dict[str, int]:
        """获取统计信息"""
        stats = {
            "pending": 0,
            "confirmed": 0,
            "rejected": 0,
            "timeout": 0,
            "auto": 0,
        }
        
        for record in self._records.values():
            stats[record.status.value] += 1
        
        return stats


# 全局单例
_confirmation_manager: Optional[ConfirmationManager] = None


def get_confirmation_manager() -> ConfirmationManager:
    """获取 ConfirmationManager 单例"""
    global _confirmation_manager
    if _confirmation_manager is None:
        _confirmation_manager = ConfirmationManager()
    return _confirmation_manager