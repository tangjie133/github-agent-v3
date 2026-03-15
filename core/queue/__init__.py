"""
队列系统模块

提供：
- QueueManager: 队列管理（入队、状态查询）
- IssueWorker: RQ Worker 封装
- 降级机制: Redis 不可用时本地处理
"""

from core.queue.manager import QueueManager, get_queue_manager
from core.queue.worker import IssueWorker

__all__ = [
    'QueueManager',
    'get_queue_manager',
    'IssueWorker',
]