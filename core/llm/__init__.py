"""
LLM 模块

提供统一的 LLM 接口，支持：
- Ollama（本地 GPU）
- OpenClaw（云端 API）
- 模板生成器（保底方案）
"""

from .manager import LLMManager, LLMResponse
from .ollama_client import OllamaClient, OllamaOptions
from .openclaw_client import OpenClawClient, OpenClawOptions
from .template_generator import TemplateGenerator

__all__ = [
    "LLMManager",
    "LLMResponse",
    "OllamaClient",
    "OllamaOptions",
    "OpenClawClient", 
    "OpenClawOptions",
    "TemplateGenerator",
]


def get_llm_manager() -> LLMManager:
    """获取 LLMManager 单例"""
    # 异步初始化需要 await，这里返回类便于依赖注入
    return LLMManager