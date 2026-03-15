"""
GitHub Agent V3 - Core Module

统一基础设施：
- Storage: 文件存储管理
- Config: 配置管理 (Pydantic)
- Logging: 结构化日志
- Queue: 异步队列
- Exceptions: 统一异常体系
"""

from core.storage import StorageManager, get_storage
from core.config import AgentConfig, get_config, ConfigLoader, reset_config
from core.logging import get_logger, traced, setup_logging
from core.exceptions import (
    GitHubAgentException,
    GitHubAPIError,
    GitHubAuthError,
    LLMProviderError,
    ConfigError,
    ErrorCode
)

# 向后兼容：ConfigManager 是 AgentConfig 的别名
ConfigManager = AgentConfig

__all__ = [
    # 存储
    'StorageManager',
    'get_storage',
    # 配置
    'AgentConfig',
    'ConfigManager',  # 向后兼容
    'get_config',
    'ConfigLoader',
    'reset_config',
    # 日志
    'get_logger',
    'traced',
    'setup_logging',
    # 异常
    'GitHubAgentException',
    'GitHubAPIError',
    'GitHubAuthError',
    'LLMProviderError',
    'ConfigError',
    'ErrorCode',
]
