"""
Ollama 专用客户端

提供 Ollama API 的封装和连接池管理
"""

import asyncio
from typing import Optional, Dict, Any, AsyncGenerator
from dataclasses import dataclass

import aiohttp

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OllamaOptions:
    """Ollama 生成选项"""
    temperature: float = 0.7
    num_ctx: int = 8192
    num_predict: int = -1  # -1 = 无限制
    top_p: float = 0.9
    top_k: int = 40
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "temperature": self.temperature,
            "num_ctx": self.num_ctx,
            "num_predict": self.num_predict,
            "top_p": self.top_p,
            "top_k": self.top_k,
        }


class OllamaClient:
    """
    Ollama 客户端
    
    功能：
    - 生成文本
    - 流式输出
    - 模型管理
    - 健康检查
    """
    
    def __init__(self, host: str = "http://localhost:11434"):
        self.host = host.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(2)  # 限制并发数
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def generate(self,
                      model: str,
                      prompt: str,
                      options: Optional[OllamaOptions] = None,
                      timeout: float = 300) -> Dict[str, Any]:
        """
        生成文本
        
        Args:
            model: 模型名称，如 "qwen3-coder:30b"
            prompt: 提示词
            options: 生成选项
            timeout: 超时时间（秒）
        
        Returns:
            Ollama API 响应
        """
        async with self._semaphore:  # 限制并发
            session = await self._get_session()
            
            payload = {
                "model": model,
                "prompt": prompt,
                "stream": False,
                "options": options.to_dict() if options else OllamaOptions().to_dict()
            }
            
            async with session.post(
                f"{self.host}/api/generate",
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                resp.raise_for_status()
                return await resp.json()
    
    async def generate_stream(self,
                             model: str,
                             prompt: str,
                             options: Optional[OllamaOptions] = None) -> AsyncGenerator[str, None]:
        """
        流式生成文本
        
        Yields:
            生成的文本片段
        """
        session = await self._get_session()
        
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": True,
            "options": options.to_dict() if options else OllamaOptions().to_dict()
        }
        
        async with session.post(
            f"{self.host}/api/generate",
            json=payload
        ) as resp:
            resp.raise_for_status()
            
            async for line in resp.content:
                if line:
                    import json
                    try:
                        data = json.loads(line)
                        if "response" in data:
                            yield data["response"]
                        if data.get("done", False):
                            break
                    except json.JSONDecodeError:
                        continue
    
    async def list_models(self) -> list:
        """列出本地可用模型"""
        session = await self._get_session()
        
        async with session.get(f"{self.host}/api/tags") as resp:
            resp.raise_for_status()
            data = await resp.json()
            return [m["name"] for m in data.get("models", [])]
    
    async def pull_model(self, model: str) -> bool:
        """拉取模型（异步操作，可能很慢）"""
        session = await self._get_session()
        
        try:
            async with session.post(
                f"{self.host}/api/pull",
                json={"name": model, "stream": False},
                timeout=aiohttp.ClientTimeout(total=600)  # 10分钟超时
            ) as resp:
                resp.raise_for_status()
                return True
        except Exception as e:
            logger.error("ollama.pull_failed", model=model, error=str(e))
            return False
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.host}/api/tags",
                timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                return resp.status == 200
        except Exception:
            return False
    
    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()