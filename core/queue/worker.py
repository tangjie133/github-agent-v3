"""
RQ Worker 封装

处理 Issue 的实际工作进程
"""

import asyncio
import signal
import sys
from typing import Optional, Callable
from datetime import datetime, timezone
from core.utils import utc_now

# RQ 仅用于与 Redis 交互，Worker 是自定义异步实现
# 如需 RQ 原生 Worker，使用: from rq import Worker

from core.logging import get_logger, traced, bind_context
from core.queue.manager import QueueManager, get_queue_manager, QueueEntry, QueueStatus
from core.storage import get_storage

logger = get_logger(__name__)


class IssueWorker:
    """
    Issue 处理 Worker
    
    职责：
    1. 从队列取出任务
    2. 调用处理器
    3. 记录结果
    4. 异常处理
    """
    
    def __init__(self,
                 worker_id: str,
                 queue_manager: Optional[QueueManager] = None,
                 processor: Optional[Callable] = None):
        self.worker_id = worker_id
        self.queue_manager = queue_manager  # 可能在 start() 中初始化
        self.processor = processor  # Issue 处理函数
        self._running = False
        self._current_entry: Optional[QueueEntry] = None
    
    async def start(self):
        """启动 Worker"""
        self._running = True
        consecutive_errors = 0
        max_backoff = 60  # 最大退避时间（秒）
        
        # 如果未提供 queue_manager，异步获取
        if self.queue_manager is None:
            self.queue_manager = await get_queue_manager()
        
        logger.info("worker.started", 
                   worker_id=self.worker_id,
                   queue_manager_id=id(self.queue_manager),
                   has_processor=bool(self.processor))
        
        # 确保队列连接
        await self.queue_manager.connect()
        logger.info("worker.queue_connected", worker_id=self.worker_id)
        
        while self._running:
            try:
                # 取出任务
                entry = await self.queue_manager.dequeue()
                
                if entry is None:
                    # 队列为空，等待
                    logger.debug("worker.queue_empty", worker_id=self.worker_id)
                    await asyncio.sleep(1)
                    consecutive_errors = 0  # 重置错误计数
                    continue
                
                # 处理任务（带超时）
                await self._process_entry_with_timeout(entry)
                consecutive_errors = 0  # 重置错误计数
                
            except Exception as e:
                consecutive_errors += 1
                # 指数退避：5s, 10s, 20s, 40s... 最大 60s
                backoff = min(5 * (2 ** consecutive_errors), max_backoff)
                
                logger.error("worker.loop_error",
                           worker_id=self.worker_id,
                           consecutive_errors=consecutive_errors,
                           backoff_seconds=backoff,
                           error_type=type(e).__name__,
                           error_message=str(e))
                
                await asyncio.sleep(backoff)
    
    async def _process_entry_with_timeout(self, entry: QueueEntry, timeout: float = 600):
        """处理单个条目（带超时保护）"""
        self._current_entry = entry
        start_time = utc_now()
        
        try:
            # 使用超时包装处理
            result = await asyncio.wait_for(
                self._process_entry(entry),
                timeout=timeout
            )
            return result
            
        except asyncio.TimeoutError:
            process_time = (utc_now() - start_time).total_seconds()
            logger.error("worker.process_timeout",
                       worker_id=self.worker_id,
                       issue_id=entry.issue_id,
                       timeout_seconds=timeout,
                       duration_seconds=process_time)
            
            # 标记为超时失败
            await self.queue_manager.complete(
                entry.issue_id,
                success=False,
                error=f"Processing timeout (>{timeout} seconds)",
                process_time=process_time
            )
            
        finally:
            self._current_entry = None
    
    async def _process_entry(self, entry: QueueEntry):
        """处理单个条目（实际处理逻辑）"""
        start_time = utc_now()
        
        # 绑定上下文（用于日志追踪）
        with bind_context(
            worker_id=self.worker_id,
            trace_id=entry.issue_id,
            repo=entry.repo,
            issue_number=entry.issue_number
        ):
            logger.info("worker.processing",
                       issue_id=entry.issue_id,
                       repo=entry.repo)
            
            try:
                # 调用处理器
                if self.processor:
                    result = await self.processor(entry)
                    
                    process_time = (utc_now() - start_time).total_seconds()
                    
                    # 标记完成
                    await self.queue_manager.complete(
                        entry.issue_id,
                        success=True,
                        result=result,
                        process_time=process_time
                    )
                    
                    logger.info("worker.completed",
                              issue_id=entry.issue_id,
                              duration_seconds=process_time)
                else:
                    # 没有处理器，直接完成
                    await self.queue_manager.complete(
                        entry.issue_id,
                        success=False,
                        error="No processor configured",
                        process_time=0
                    )
                    
            except Exception as e:
                process_time = (utc_now() - start_time).total_seconds()
                
                logger.error("worker.failed",
                           issue_id=entry.issue_id,
                           error_type=type(e).__name__,
                           error_message=str(e),
                           duration_seconds=process_time)
                
                # 标记失败
                await self.queue_manager.complete(
                    entry.issue_id,
                    success=False,
                    error=f"{type(e).__name__}: {str(e)}",
                    process_time=process_time
                )
            
            finally:
                self._current_entry = None
    
    def stop(self):
        """停止 Worker"""
        self._running = False
        logger.info("worker.stopping", worker_id=self.worker_id)
        
        # 如果正在处理，记录状态
        if self._current_entry:
            logger.warning("worker.interrupted",
                         issue_id=self._current_entry.issue_id)


class WorkerPool:
    """
    Worker 池
    
    管理多个 Worker 进程
    """
    
    def __init__(self, 
                 num_workers: int = 4,
                 processor: Optional[Callable] = None):
        self.num_workers = num_workers
        self.processor = processor
        self.workers: list[IssueWorker] = []
        self._tasks: list[asyncio.Task] = []
    
    async def start(self):
        """启动所有 Worker"""
        logger.info("worker_pool.starting", num_workers=self.num_workers)
        
        # 获取共享的 queue_manager 实例
        queue_manager = await get_queue_manager()
        logger.info("worker_pool.queue_manager_ready", 
                   queue_manager_id=id(queue_manager))
        
        for i in range(self.num_workers):
            worker = IssueWorker(
                worker_id=f"worker-{i+1}",
                queue_manager=queue_manager,  # 共享实例
                processor=self.processor
            )
            self.workers.append(worker)
            
            # 启动 Worker（不等待）
            task = asyncio.create_task(worker.start())
            self._tasks.append(task)
        
        logger.info("worker_pool.started", num_workers=self.num_workers)
    
    async def stop(self):
        """停止所有 Worker"""
        logger.info("worker_pool.stopping")
        
        # 停止所有 Worker
        for worker in self.workers:
            worker.stop()
        
        # 等待任务结束
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        
        logger.info("worker_pool.stopped")
    
    def get_stats(self) -> dict:
        """获取 Worker 统计"""
        return {
            "total": self.num_workers,
            "running": len([w for w in self.workers if w._running]),
            "busy": len([w for w in self.workers if w._current_entry]),
        }
