"""
LLM Manager

统一的 LLM 管理器，实现三层策略：
1. Ollama（本地 GPU，32GB，30B 模型）
2. OpenClaw（云端 API）
3. 模板生成器（保底方案）
"""

import asyncio
import time
from enum import Enum
from typing import Optional, Dict, Any
from dataclasses import dataclass

from core.logging import get_logger, traced
from core.config import get_config
from core.llm.ollama_client import OllamaClient, OllamaOptions
from core.llm.openclaw_client import OpenClawClient, OpenClawOptions
from core.llm.template_generator import TemplateGenerator

logger = get_logger(__name__)


class LLMProvider(Enum):
    """LLM 提供商枚举"""
    OLLAMA = "ollama"
    OPENCLAW = "openclaw"
    TEMPLATE = "template"


@dataclass
class LLMResponse:
    """LLM 响应"""
    text: str
    provider: LLMProvider
    model: str
    latency_ms: int
    tokens_used: Optional[int] = None
    finish_reason: Optional[str] = None


class LLMManager:
    """
    LLM 管理器
    
    负责：
    - 统一管理多个 LLM 提供商
    - 实现自动 fallback 策略
    - 追踪性能和错误
    """
    
    def __init__(self):
        config = get_config()
        
        # 配置
        self.primary_provider = LLMProvider(config.llm.primary_provider)
        self.fallback_provider = LLMProvider(config.llm.fallback_provider)
        
        # 客户端
        self._ollama: Optional[OllamaClient] = None
        self._openclaw: Optional[OpenClawClient] = None
        self._template: Optional[TemplateGenerator] = None
        
        # 统计
        self._stats: Dict[str, Dict[str, Any]] = {
            "ollama": {"success": 0, "failure": 0, "latency_ms": []},
            "openclaw": {"success": 0, "failure": 0, "latency_ms": []},
            "template": {"success": 0, "failure": 0, "latency_ms": []},
        }
    
    def _get_ollama(self) -> OllamaClient:
        """获取或创建 Ollama 客户端"""
        if self._ollama is None:
            config = get_config()
            self._ollama = OllamaClient(config.llm.ollama_host)
        return self._ollama
    
    def _get_openclaw(self) -> Optional[OpenClawClient]:
        """获取或创建 OpenClaw 客户端"""
        if self._openclaw is None:
            config = get_config()
            if config.llm.openclaw_enabled:
                # 从环境变量获取 API key
                import os
                api_key = os.getenv("OPENCLAW_API_KEY")
                if api_key:
                    self._openclaw = OpenClawClient(
                        api_key=api_key,
                        base_url=config.llm.openclaw_url
                    )
        return self._openclaw
    
    def _get_template(self) -> TemplateGenerator:
        """获取模板生成器"""
        if self._template is None:
            self._template = TemplateGenerator()
        return self._template
    
    @traced("llm.generate")
    async def generate(self,
                      prompt: str,
                      task_type: str = "code",
                      max_retries: int = 2,
                      timeout: Optional[float] = None) -> LLMResponse:
        """
        生成文本，自动处理 fallback
        
        Args:
            prompt: 提示词
            task_type: 任务类型（code/intent/answer）
            max_retries: 最大重试次数
            timeout: 超时时间
        
        Returns:
            LLM 响应
        """
        errors = []
        
        # 尝试主提供商
        for attempt in range(max_retries):
            try:
                logger.info("llm.try_primary",
                           provider=self.primary_provider.value,
                           attempt=attempt + 1)
                
                response = await self._try_generate(
                    self.primary_provider, prompt, task_type, timeout
                )
                
                self._stats[self.primary_provider.value]["success"] += 1
                return response
                
            except Exception as e:
                errors.append(f"{self.primary_provider.value}: {e}")
                self._stats[self.primary_provider.value]["failure"] += 1
                logger.warning("llm.primary_failed",
                              error=str(e),
                              attempt=attempt + 1)
                
                if attempt < max_retries - 1:
                    await asyncio.sleep(1 * (2 ** attempt))  # 指数退避
        
        # 尝试 fallback
        if self.fallback_provider != self.primary_provider:
            try:
                logger.info("llm.try_fallback",
                           provider=self.fallback_provider.value)
                
                response = await self._try_generate(
                    self.fallback_provider, prompt, task_type, timeout
                )
                
                self._stats[self.fallback_provider.value]["success"] += 1
                return response
                
            except Exception as e:
                errors.append(f"{self.fallback_provider.value}: {e}")
                self._stats[self.fallback_provider.value]["failure"] += 1
                logger.warning("llm.fallback_failed", error=str(e))
        
        # 使用模板生成器
        logger.warning("llm.using_template",
                      errors="; ".join(errors))
        
        template = self._get_template()
        start = time.time()
        text = await template.generate_response(prompt)
        latency = int((time.time() - start) * 1000)
        
        self._stats["template"]["success"] += 1
        
        return LLMResponse(
            text=text,
            provider=LLMProvider.TEMPLATE,
            model="template",
            latency_ms=latency
        )
    
    async def _try_generate(self,
                           provider: LLMProvider,
                           prompt: str,
                           task_type: str,
                           timeout: Optional[float]) -> LLMResponse:
        """
        尝试使用指定提供商生成
        """
        config = get_config()
        start = time.time()
        
        if provider == LLMProvider.OLLAMA:
            client = self._get_ollama()
            
            # 根据任务类型选择模型
            model_map = {
                "intent": config.llm.ollama_model_intent,
                "code": config.llm.ollama_model_code,
                "answer": config.llm.ollama_model_answer,
            }
            model = model_map.get(task_type, config.llm.ollama_model_code)
            
            result = await client.generate(
                model=model,
                prompt=prompt,
                options=OllamaOptions(
                    temperature=0.7,
                    num_ctx=8192,
                ),
                timeout=timeout or config.llm.ollama_timeout
            )
            
            latency = int((time.time() - start) * 1000)
            
            return LLMResponse(
                text=result["response"],
                provider=provider,
                model=model,
                latency_ms=latency,
                tokens_used=result.get("eval_count")
            )
        
        elif provider == LLMProvider.OPENCLAW:
            client = self._get_openclaw()
            if not client:
                raise RuntimeError("OpenClaw not configured")
            
            system_prompt = self._get_system_prompt(task_type)
            
            text = await client.generate(
                prompt=prompt,
                system=system_prompt,
                options=OpenClawOptions(
                    temperature=0.7,
                    max_tokens=8192,
                )
            )
            
            latency = int((time.time() - start) * 1000)
            
            return LLMResponse(
                text=text,
                provider=provider,
                model="kimi-k2.5",  # 或其他配置的模型
                latency_ms=latency
            )
        
        else:
            raise ValueError(f"Unknown provider: {provider}")
    
    def _get_system_prompt(self, task_type: str) -> str:
        """获取任务类型的系统提示词"""
        prompts = {
            "intent": """你是一个 Issue 分析助手。请分析 GitHub Issue 的内容，
判断是否需要代码修复。只回复 "FIX" 或 "ANSWER"。""",
            "code": """你是一个专业的代码修复助手。请分析代码问题并提供修复方案。
你的回复应该包含：
1. 问题分析
2. 修复后的代码
3. 修改说明""",
            "answer": """你是一个技术支持助手。请回答用户关于代码库的问题。
提供清晰、准确的解释和示例。""",
        }
        return prompts.get(task_type, prompts["code"])
    
    async def health_check(self) -> Dict[str, bool]:
        """
        检查所有提供商的健康状态
        
        Returns:
            提供商名称 -> 健康状态 的映射
        """
        results = {}
        
        # Ollama
        try:
            ollama = self._get_ollama()
            results["ollama"] = await ollama.health_check()
        except Exception as e:
            logger.warning("llm.health.ollama_failed", error=str(e))
            results["ollama"] = False
        
        # OpenClaw
        try:
            openclaw = self._get_openclaw()
            if openclaw:
                results["openclaw"] = await openclaw.health_check()
            else:
                results["openclaw"] = False
        except Exception as e:
            logger.warning("llm.health.openclaw_failed", error=str(e))
            results["openclaw"] = False
        
        # Template 总是可用
        results["template"] = True
        
        return results
    
    def get_stats(self) -> Dict[str, Dict[str, Any]]:
        """获取统计信息"""
        return self._stats.copy()
    
    async def close(self):
        """关闭所有客户端连接"""
        if self._ollama:
            await self._ollama.close()
        if self._openclaw:
            await self._openclaw.close()


# 全局单例
_llm_manager: Optional[LLMManager] = None
_llm_lock = asyncio.Lock()


async def get_llm_manager() -> LLMManager:
    """获取 LLMManager 单例"""
    global _llm_manager
    if _llm_manager is None:
        async with _llm_lock:
            if _llm_manager is None:
                _llm_manager = LLMManager()
    return _llm_manager