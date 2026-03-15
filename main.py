"""
GitHub Agent V3 - 主入口

启动 Webhook 服务器、Worker 池和知识库服务
"""

# 首先加载 .env 文件，确保环境变量在导入其他模块前已设置
from dotenv import load_dotenv
load_dotenv('.env')

import asyncio
import signal
import sys
import threading
from typing import Optional
from http.server import HTTPServer

from core.logging import get_logger, setup_logging
from core.config import get_config
from core.queue.worker import WorkerPool
from services.processor import get_issue_processor
from services.webhook_server import start_server

logger = get_logger(__name__)


class GitHubAgent:
    """
    GitHub Agent 主服务
    
    整合 Webhook 服务器、Worker 池和知识库服务
    """
    
    def __init__(self):
        self.config = get_config()
        self.worker_pool: Optional[WorkerPool] = None
        self.webhook_task: Optional[asyncio.Task] = None
        self._shutdown_event = asyncio.Event()
        self._kb_server: Optional[HTTPServer] = None
        self._kb_thread: Optional[threading.Thread] = None
    
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
                issue_body=entry.body,
                installation_id=entry.installation_id
            )
        
        return process_entry
    
    def _start_kb_service(self):
        """在后台线程启动知识库服务"""
        try:
            from knowledge_base.kb_service import KnowledgeBaseService, KBRequestHandler, run_server
            
            # 从配置获取知识库设置
            kb_config = self.config.knowledge_base
            if not kb_config.enabled:
                logger.info("kb.disabled")
                return
            
            # 解析 host:port
            service_url = kb_config.service_url  # 如 "http://localhost:8000"
            host = "0.0.0.0"
            port = 8000
            
            if ":" in service_url:
                parts = service_url.replace("http://", "").replace("https://", "").split(":")
                if len(parts) == 2:
                    host = parts[0]
                    port = int(parts[1])
            
            # 获取嵌入模型配置
            embedding_model = getattr(kb_config, 'embedding_model', 'nomic-embed-text')
            embedding_host = getattr(kb_config, 'embedding_host', 'http://localhost:11434')
            
            logger.info("kb.starting",
                       host=host,
                       port=port,
                       embedding_model=embedding_model)
            
            # 创建并启动知识库服务
            kb_service = KnowledgeBaseService(
                embedding_model=embedding_model,
                embedding_host=embedding_host
            )
            
            KBRequestHandler.kb_service = kb_service
            
            self._kb_server = HTTPServer((host, port), KBRequestHandler)
            logger.info(f"知识库服务已启动 http://{host}:{port}")
            
            # 在后台线程运行
            self._kb_thread = threading.Thread(
                target=self._kb_server.serve_forever,
                daemon=True
            )
            self._kb_thread.start()
            logger.info("kb.started", host=host, port=port)
            
        except Exception as e:
            logger.error("kb.failed", error=str(e))
    
    def _stop_kb_service(self):
        """停止知识库服务"""
        if self._kb_server:
            try:
                self._kb_server.shutdown()
                logger.info("kb.stopped")
            except Exception as e:
                logger.warning("kb.stop_failed", error=str(e))
    
    async def start(self):
        """启动所有服务"""
        logger.info("agent.starting",
                   version="3.0.0",
                   confirm_mode=self.config.processing.confirm_mode)
        
        # 1. 启动知识库服务（后台线程）
        self._start_kb_service()
        
        # 2. 创建 Issue 处理器
        processor = await self._create_processor()
        
        # 3. 启动 Worker 池
        self.worker_pool = WorkerPool(
            num_workers=self.config.queue.workers,
            processor=processor
        )
        await self.worker_pool.start()
        
        # 4. 启动 Webhook 服务器
        self.webhook_task = asyncio.create_task(
            start_server(
                host=self.config.webhook.host,
                port=self.config.webhook.port
            )
        )
        
        logger.info("agent.started",
                   workers=self.config.queue.workers,
                   webhook_port=self.config.webhook.port,
                   kb_enabled=self.config.knowledge_base.enabled)
        
        # 等待关闭信号
        await self._shutdown_event.wait()
    
    async def stop(self):
        """停止所有服务"""
        logger.info("agent.stopping")
        
        # 停止知识库服务
        self._stop_kb_service()
        
        # 取消 Webhook 任务（Uvicorn 服务器）
        if self.webhook_task and not self.webhook_task.done():
            self.webhook_task.cancel()
            try:
                await asyncio.wait_for(self.webhook_task, timeout=6)
            except asyncio.TimeoutError:
                logger.warning("agent.stop_timeout", component="webhook")
            except CancelledError:
                pass
        
        # 停止 Worker 池
        if self.worker_pool:
            await asyncio.wait_for(self.worker_pool.stop(), timeout=10)
        
        logger.info("agent.stopped")
    
    def shutdown(self):
        """触发关闭"""
        self._shutdown_event.set()


async def main():
    """主入口"""
    # 设置日志 - 使用配置的数据目录和日志级别
    from core.config import get_config
    
    # 先加载配置，确保环境变量被读取
    config = get_config()
    
    # 使用配置中的数据目录
    logs_dir = config.storage.datadir / 'logs'
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    # 从配置读取日志设置
    log_level = config.logging.level if hasattr(config, 'logging') else 'INFO'
    json_file = getattr(config.logging, 'json_file', True)
    text_file = getattr(config.logging, 'text_file', True)
    
    setup_logging(logs_dir, level=log_level, json_file=json_file, text_file=text_file)
    
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
