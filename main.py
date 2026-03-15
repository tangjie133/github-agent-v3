"""
GitHub Agent V3 - 主入口

启动 Webhook 服务器和 Worker 池
"""

import asyncio
import signal
import sys
from typing import Optional

from core.logging import get_logger, setup_logging
from core.config import get_config
from core.queue.worker import WorkerPool
from services.processor import get_issue_processor
from services.webhook_server import start_server

logger = get_logger(__name__)


class GitHubAgent:
    """
    GitHub Agent 主服务
    
    整合 Webhook 服务器和 Worker 池
    """
    
    def __init__(self):
        self.config = get_config()
        self.worker_pool: Optional[WorkerPool] = None
        self.webhook_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
    
    async def _create_processor(self):
        """创建 Issue 处理器"""
        processor = await get_issue_processor()
        
        # 返回包装函数，适配 Worker 接口
        async def process_entry(entry):
            """处理队列条目"""
            return await processor.handle_issue(
                owner=entry.owner,
                repo=entry.repo,
                issue_number=entry.issue_number,
                issue_title=entry.title,
                issue_body=entry.body
            )
        
        return process_entry
    
    async def start(self):
        """启动所有服务"""
        logger.info("agent.starting",
                   version="3.0.0",
                   confirm_mode=self.config.processing.confirm_mode)
        
        # 创建 Issue 处理器
        processor = await self._create_processor()
        
        # 启动 Worker 池
        self.worker_pool = WorkerPool(
            num_workers=self.config.queue.workers,
            processor=processor
        )
        await self.worker_pool.start()
        
        # 启动 Webhook 服务器
        self.webhook_task = asyncio.create_task(
            start_server(
                host="0.0.0.0",
                port=8000
            )
        )
        
        logger.info("agent.started",
                   workers=self.config.queue.workers,
                   webhook_port=8000)
        
        # 等待关闭信号
        await self._shutdown_event.wait()
    
    async def stop(self):
        """停止所有服务"""
        logger.info("agent.stopping")
        
        # 停止 Worker 池
        if self.worker_pool:
            await self.worker_pool.stop()
        
        # 取消 Webhook 任务
        if self.webhook_task:
            self.webhook_task.cancel()
            try:
                await self.webhook_task
            except asyncio.CancelledError:
                pass
        
        logger.info("agent.stopped")
    
    def shutdown(self):
        """触发关闭"""
        self._shutdown_event.set()


async def main():
    """主入口"""
    # 设置日志（简化版，使用临时目录）
    from pathlib import Path
    import tempfile
    logs_dir = Path(tempfile.gettempdir()) / "github-agent-logs"
    logs_dir.mkdir(exist_ok=True)
    setup_logging(logs_dir)
    
    agent = GitHubAgent()
    
    # 信号处理
    def signal_handler(sig, frame):
        logger.info("agent.signal_received", signal=sig)
        agent.shutdown()
    
    signal.signal(signal.SIGINT, signal_handler)
    signal.signal(signal.SIGTERM, signal_handler)
    
    try:
        await agent.start()
    except Exception as e:
        logger.error("agent.error", error=str(e))
        raise
    finally:
        await agent.stop()


if __name__ == "__main__":
    asyncio.run(main())