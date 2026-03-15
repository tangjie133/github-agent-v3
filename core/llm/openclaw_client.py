"""
OpenClaw 客户端

使用 HTTP API 调用 OpenClaw（或使用 OpenAI 兼容接口）
"""

import asyncio
from typing import Optional, Dict, Any, AsyncGenerator
from dataclasses import dataclass

import aiohttp

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class OpenClawOptions:
    """OpenClaw 生成选项"""
    model: str = "kimi-k2.5"
    temperature: float = 0.7
    max_tokens: int = 8192
    top_p: float = 0.9
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
        }


class OpenClawClient:
    """
    OpenClaw 客户端
    
    使用 OpenAI 兼容的 API 接口
    """
    
    def __init__(self, api_key: str, base_url: str = "https://api.moonshot.cn/v1"):
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self._session: Optional[aiohttp.ClientSession] = None
        self._semaphore = asyncio.Semaphore(5)  # 限制并发数
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取或创建 session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def chat_completion(self,
                             messages: list,
                             options: Optional[OpenClawOptions] = None,
                             timeout: float = 120) -> str:
        """
        对话完成
        
        Args:
            messages: 消息列表，格式为 [{"role": "system/user", "content": "..."}]
            options: 生成选项
            timeout: 超时时间（秒）
        
        Returns:
            生成的文本
        """
        async with self._semaphore:  # 限制并发
            session = await self._get_session()
            
            opts = options or OpenClawOptions()
            
            payload = {
                "model": opts.model,
                "messages": messages,
                **opts.to_dict()
            }
            
            async with session.post(
                f"{self.base_url}/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json"
                },
                json=payload,
                timeout=aiohttp.ClientTimeout(total=timeout)
            ) as resp:
                resp.raise_for_status()
                data = await resp.json()
                return data["choices"][0]["message"]["content"]
    
    async def generate(self,
                      prompt: str,
                      system: Optional[str] = None,
                      options: Optional[OpenClawOptions] = None) -> str:
        """
        简单生成接口（适配 LLMBase 接口）
        
        Args:
            prompt: 提示词
            system: 系统提示词
            options: 生成选项
        
        Returns:
            生成的文本
        """
        messages = []
        
        if system:
            messages.append({"role": "system", "content": system})
        
        messages.append({"role": "user", "content": prompt})
        
        return await self.chat_completion(messages, options)
    
    async def health_check(self) -> bool:
        """健康检查"""
        try:
            session = await self._get_session()
            async with session.get(
                f"{self.base_url}/models",
                headers={"Authorization": f"Bearer {self.api_key}"},
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