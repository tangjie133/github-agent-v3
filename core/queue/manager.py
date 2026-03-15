"""
队列管理器

管理 Issue 处理队列：
- 入队/出队
- 状态查询
- 排队提示
- 降级处理（Redis 不可用时本地处理）
"""

import json
import asyncio
import time
from enum import Enum
from typing import Optional, Dict, Any, List
from dataclasses import dataclass, asdict
from datetime import datetime
from core.utils import utc_now_iso
from contextlib import asynccontextmanager

import redis.asyncio as redis
from redis.exceptions import ConnectionError, TimeoutError

from core.logging import get_logger, traced
from core.storage import get_storage

logger = get_logger(__name__)


class QueueStatus(Enum):
    """队列状态"""
    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


class Priority(Enum):
    """优先级"""
    LOW = 1
    NORMAL = 2
    HIGH = 3
    URGENT = 4


@dataclass
class QueueEntry:
    """队列条目"""
    issue_id: str
    repo: str
    issue_number: int
    event_type: str = "issues"
    priority: int = 2  # Priority.NORMAL.value
    status: QueueStatus = QueueStatus.PENDING
    created_at: str = ""
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    result: Optional[Dict] = None
    error: Optional[str] = None
    # 扩展字段
    owner: str = ""
    title: str = ""
    body: str = ""
    
    def __post_init__(self):
        if not self.created_at:
            self.created_at = utc_now_iso()
    
    def to_dict(self) -> Dict[str, Any]:
        data = asdict(self)
        data['status'] = self.status.value
        return data
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'QueueEntry':
        data['status'] = QueueStatus(data['status'])
        return cls(**data)


@dataclass  
class QueuePosition:
    """排队位置信息"""
    issue_id: str
    position: int
    total_queued: int
    estimated_wait_seconds: int
    workers_busy: int
    workers_total: int
    
    def format_message(self) -> str:
        """格式化排队提示消息"""
        minutes = self.estimated_wait_seconds // 60
        seconds = self.estimated_wait_seconds % 60
        
        if self.position == 0:
            return "🔄 正在处理您的请求..."
        
        wait_str = f"{minutes}分{seconds}秒" if minutes > 0 else f"{seconds}秒"
        
        return f"""⏳ 排队提示

当前位置：**第 {self.position} 位** / 共 {self.total_queued} 人
预计等待：**{wait_str}**
处理进度：{self.workers_busy}/{self.workers_total} Worker 忙碌

您的请求已加入队列，处理完成后会自动回复。

如急需处理，请回复 " urgent" 优先处理，或联系管理员。
"""


class QueueManager:
    """
    队列管理器
    
    功能：
    1. 入队/出队管理
    2. 状态追踪
    3. 排队提示
    4. Redis 降级（本地 SQLite）
    """
    
    def __init__(self, 
                 redis_url: str = "redis://localhost:6379/0",
                 workers_total: int = 4,
                 avg_process_time: float = 30.0):
        self.redis_url = redis_url
        self.workers_total = workers_total
        self.avg_process_time = avg_process_time  # 平均处理时间（动态更新）
        
        self._redis: Optional[redis.Redis] = None
        self._redis_available = False
        
        # 队列键名
        self.queue_key = "github_agent:queue"
        self.processing_key = "github_agent:processing"
        self.entry_key_prefix = "github_agent:entry:"
        
        # 本地降级存储（Redis 不可用时使用）
        self._local_queue: List[QueueEntry] = []
        self._local_processing: Dict[str, QueueEntry] = {}
    
    async def connect(self) -> bool:
        """连接 Redis，返回是否成功"""
        try:
            self._redis = redis.from_url(self.redis_url, decode_responses=True)
            await self._redis.ping()
            self._redis_available = True
            logger.info("queue.redis_connected", url=self.redis_url)
            return True
        except (ConnectionError, TimeoutError) as e:
            logger.warning("queue.redis_unavailable", 
                          error_type=type(e).__name__,
                          fallback="local")
            self._redis_available = False
            return False
    
    async def disconnect(self):
        """断开连接"""
        if self._redis:
            await self._redis.close()
            self._redis = None
    
    @property
    def is_available(self) -> bool:
        """Redis 是否可用"""
        return self._redis_available and self._redis is not None
    
    async def _ensure_connection(self) -> bool:
        """确保连接可用（自动重连）"""
        if not self._redis_available or self._redis is None:
            logger.debug("queue.reconnecting")
            return await self.connect()
        
        try:
            # 测试连接
            await self._redis.ping()
            return True
        except (ConnectionError, TimeoutError) as e:
            logger.warning("queue.connection_lost", error_type=type(e).__name__)
            self._redis_available = False
            return await self.connect()
    
    @traced("enqueue")
    async def enqueue(self,
                     issue_id: str,
                     repo: str, 
                     issue_number: int,
                     event_type: str = "issue_comment",
                     priority: int = 0) -> QueuePosition:
        """
        将 Issue 加入队列
        
        Args:
            issue_id: 唯一标识，如 "owner/repo#123"
            repo: 仓库全名
            issue_number: Issue 编号
            event_type: 事件类型
            priority: 优先级（0=普通，1=高，2=紧急）
        
        Returns:
            QueuePosition: 排队位置信息
        """
        entry = QueueEntry(
            issue_id=issue_id,
            repo=repo,
            issue_number=issue_number,
            event_type=event_type,
            priority=priority,
            status=QueueStatus.QUEUED,
            created_at=utc_now_iso()
        )
        
        if self.is_available:
            return await self._enqueue_redis(entry)
        else:
            return await self._enqueue_local(entry)
    
    async def _enqueue_redis(self, entry: QueueEntry) -> QueuePosition:
        """使用 Redis 入队"""
        # 确保连接
        if not await self._ensure_connection():
            # 连接失败，降级到本地
            logger.warning("queue.redis_unavailable_fallback")
            return await self._enqueue_local(entry)
        
        # 检查是否已存在
        exists = await self._redis.exists(f"{self.entry_key_prefix}{entry.issue_id}")
        if exists:
            # 返回现有位置
            return await self.get_position(entry.issue_id)
        
        # 计算分数（优先级 + 时间戳）
        # 优先级高的排在前面，同优先级按时间先后
        score = entry.priority * 1000000000 + int(time.time())
        
        # 加入有序集合
        await self._redis.zadd(self.queue_key, {entry.issue_id: score})
        
        # 存储条目详情
        await self._redis.setex(
            f"{self.entry_key_prefix}{entry.issue_id}",
            3600,  # 1小时过期
            json.dumps(entry.to_dict())
        )
        
        logger.info("queue.enqueued",
                   issue_id=entry.issue_id,
                   repo=entry.repo,
                   priority=entry.priority)
        
        return await self.get_position(entry.issue_id)
    
    async def _enqueue_local(self, entry: QueueEntry) -> QueuePosition:
        """本地降级入队"""
        # 检查是否已存在
        for i, e in enumerate(self._local_queue):
            if e.issue_id == entry.issue_id:
                return QueuePosition(
                    issue_id=entry.issue_id,
                    position=i + 1,
                    total_queued=len(self._local_queue),
                    estimated_wait_seconds=int((i + 1) * self.avg_process_time),
                    workers_busy=len(self._local_processing),
                    workers_total=self.workers_total
                )
        
        # 按优先级插入
        insert_pos = len(self._local_queue)
        for i, e in enumerate(self._local_queue):
            if e.priority < entry.priority:
                insert_pos = i
                break
        
        self._local_queue.insert(insert_pos, entry)
        
        logger.info("queue.enqueued_local",
                   issue_id=entry.issue_id,
                   repo=entry.repo,
                   queue_size=len(self._local_queue))
        
        return QueuePosition(
            issue_id=entry.issue_id,
            position=insert_pos + 1,
            total_queued=len(self._local_queue),
            estimated_wait_seconds=int((insert_pos + 1) * self.avg_process_time),
            workers_busy=len(self._local_processing),
            workers_total=self.workers_total
        )
    
    async def dequeue(self) -> Optional[QueueEntry]:
        """取出下一个要处理的条目"""
        if self.is_available:
            return await self._dequeue_redis()
        else:
            return await self._dequeue_local()
    
    async def _dequeue_redis(self) -> Optional[QueueEntry]:
        """从 Redis 出队"""
        # 确保连接
        if not await self._ensure_connection():
            logger.warning("queue.redis_unavailable_fallback")
            return await self._dequeue_local()
        
        # 获取队列第一个
        items = await self._redis.zrange(self.queue_key, 0, 0)
        if not items:
            return None
        
        issue_id = items[0]
        
        # 从队列移除
        await self._redis.zrem(self.queue_key, issue_id)
        
        # 加入处理中集合
        await self._redis.sadd(self.processing_key, issue_id)
        
        # 获取条目详情
        entry_data = await self._redis.get(f"{self.entry_key_prefix}{issue_id}")
        if not entry_data:
            return None
        
        entry = QueueEntry.from_dict(json.loads(entry_data))
        entry.status = QueueStatus.PROCESSING
        entry.started_at = utc_now_iso()
        
        # 更新存储
        await self._redis.setex(
            f"{self.entry_key_prefix}{issue_id}",
            3600,
            json.dumps(entry.to_dict())
        )
        
        logger.debug("queue.dequeued", issue_id=issue_id)
        return entry
    
    async def _dequeue_local(self) -> Optional[QueueEntry]:
        """本地降级出队"""
        if not self._local_queue:
            return None
        
        entry = self._local_queue.pop(0)
        entry.status = QueueStatus.PROCESSING
        entry.started_at = utc_now_iso()
        
        self._local_processing[entry.issue_id] = entry
        
        logger.debug("queue.dequeued_local", 
                    issue_id=entry.issue_id,
                    queue_size=len(self._local_queue))
        return entry
    
    async def complete(self, 
                      issue_id: str, 
                      success: bool = True,
                      result: Optional[Dict] = None,
                      error: Optional[str] = None,
                      process_time: float = 0):
        """标记处理完成"""
        if self.is_available:
            await self._complete_redis(issue_id, success, result, error)
        else:
            await self._complete_local(issue_id, success, result, error)
        
        # 更新平均处理时间
        if process_time > 0:
            self.avg_process_time = 0.9 * self.avg_process_time + 0.1 * process_time
    
    async def _complete_redis(self, issue_id: str, 
                             success: bool, result: Optional[Dict], error: Optional[str]):
        """Redis 完成处理"""
        # 确保连接
        if not await self._ensure_connection():
            logger.warning("queue.redis_unavailable_skipping_complete")
            return
        
        # 从处理中集合移除
        await self._redis.srem(self.processing_key, issue_id)
        
        # 更新条目状态
        entry_data = await self._redis.get(f"{self.entry_key_prefix}{issue_id}")
        if entry_data:
            entry = QueueEntry.from_dict(json.loads(entry_data))
            entry.status = QueueStatus.COMPLETED if success else QueueStatus.FAILED
            entry.completed_at = utc_now_iso()
            entry.result = result
            entry.error = error
            
            # 保存 5 分钟后过期
            await self._redis.setex(
                f"{self.entry_key_prefix}{issue_id}",
                300,
                json.dumps(entry.to_dict())
            )
        
        logger.info("queue.completed",
                   issue_id=issue_id,
                   success=success)
    
    async def _complete_local(self, issue_id: str,
                             success: bool, result: Optional[Dict], error: Optional[str]):
        """本地完成处理"""
        if issue_id in self._local_processing:
            entry = self._local_processing.pop(issue_id)
            entry.status = QueueStatus.COMPLETED if success else QueueStatus.FAILED
            entry.completed_at = utc_now_iso()
            entry.result = result
            entry.error = error
            
            logger.info("queue.completed_local",
                       issue_id=issue_id,
                       success=success)
    
    async def get_position(self, issue_id: str) -> Optional[QueuePosition]:
        """获取排队位置"""
        if self.is_available:
            return await self._get_position_redis(issue_id)
        else:
            return await self._get_position_local(issue_id)
    
    async def _get_position_redis(self, issue_id: str) -> Optional[QueuePosition]:
        """从 Redis 获取位置"""
        # 检查是否正在处理
        is_processing = await self._redis.sismember(self.processing_key, issue_id)
        if is_processing:
            return QueuePosition(
                issue_id=issue_id,
                position=0,
                total_queued=await self._redis.zcard(self.queue_key),
                estimated_wait_seconds=0,
                workers_busy=await self._redis.scard(self.processing_key),
                workers_total=self.workers_total
            )
        
        # 获取排名
        rank = await self._redis.zrank(self.queue_key, issue_id)
        if rank is None:
            return None
        
        # 计算等待时间
        ahead = rank
        total = await self._redis.zcard(self.queue_key)
        busy = await self._redis.scard(self.processing_key)
        available = max(1, self.workers_total - busy)
        wait_time = ahead * self.avg_process_time / available
        
        return QueuePosition(
            issue_id=issue_id,
            position=ahead + 1,
            total_queued=total,
            estimated_wait_seconds=int(wait_time),
            workers_busy=busy,
            workers_total=self.workers_total
        )
    
    async def _get_position_local(self, issue_id: str) -> Optional[QueuePosition]:
        """从本地获取位置"""
        # 检查是否正在处理
        if issue_id in self._local_processing:
            return QueuePosition(
                issue_id=issue_id,
                position=0,
                total_queued=len(self._local_queue),
                estimated_wait_seconds=0,
                workers_busy=len(self._local_processing),
                workers_total=self.workers_total
            )
        
        # 查找位置
        for i, entry in enumerate(self._local_queue):
            if entry.issue_id == issue_id:
                return QueuePosition(
                    issue_id=issue_id,
                    position=i + 1,
                    total_queued=len(self._local_queue),
                    estimated_wait_seconds=int((i + 1) * self.avg_process_time),
                    workers_busy=len(self._local_processing),
                    workers_total=self.workers_total
                )
        
        return None
    
    async def get_status(self, issue_id: str) -> Optional[QueueEntry]:
        """获取条目状态"""
        if self.is_available:
            entry_data = await self._redis.get(f"{self.entry_key_prefix}{issue_id}")
            if entry_data:
                return QueueEntry.from_dict(json.loads(entry_data))
        else:
            # 检查队列
            for entry in self._local_queue:
                if entry.issue_id == issue_id:
                    return entry
            # 检查处理中
            if issue_id in self._local_processing:
                return self._local_processing[issue_id]
        
        return None
    
    async def get_stats(self) -> Dict[str, Any]:
        """获取队列统计"""
        if self.is_available:
            return {
                "queued": await self._redis.zcard(self.queue_key),
                "processing": await self._redis.scard(self.processing_key),
                "workers_total": self.workers_total,
                "avg_process_time": self.avg_process_time,
                "backend": "redis"
            }
        else:
            return {
                "queued": len(self._local_queue),
                "processing": len(self._local_processing),
                "workers_total": self.workers_total,
                "avg_process_time": self.avg_process_time,
                "backend": "local"
            }


# 全局单例
_queue_manager: Optional[QueueManager] = None
_queue_lock = asyncio.Lock()


async def get_queue_manager(redis_url: Optional[str] = None,
                           workers_total: int = 4) -> QueueManager:
    """获取 QueueManager 单例（异步线程安全）"""
    global _queue_manager
    if _queue_manager is None:
        async with _queue_lock:
            if _queue_manager is None:  # 双重检查
                _queue_manager = QueueManager(
                    redis_url=redis_url or "redis://localhost:6379/0",
                    workers_total=workers_total
                )
                # 自动连接
                await _queue_manager.connect()
    return _queue_manager


def get_queue_manager_sync(redis_url: Optional[str] = None,
                          workers_total: int = 4) -> QueueManager:
    """同步获取 QueueManager 单例（用于非异步上下文）"""
    global _queue_manager
    if _queue_manager is None:
        _queue_manager = QueueManager(
            redis_url=redis_url or "redis://localhost:6379/0",
            workers_total=workers_total
        )
    return _queue_manager
