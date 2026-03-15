"""
统一配置管理 (Pydantic 版本)

提供类型安全、自动验证、环境变量映射的配置管理
"""

import os
import yaml
from pathlib import Path
from typing import Optional, List, Dict, Any, Literal
from functools import lru_cache
from pydantic import BaseModel, Field, field_validator, model_validator
from pydantic_settings import BaseSettings
from pydantic import ConfigDict

from core.exceptions import ConfigError


# =============================================================================
# 配置模型定义
# =============================================================================

class StorageConfig(BaseModel):
    """存储配置"""
    datadir: Path = Field(
        default_factory=lambda: Path.home() / "github-agent-data",
        description="数据存储根目录"
    )
    max_repo_size_mb: int = Field(default=1000, ge=100, le=10000)
    log_retention_days: int = Field(default=30, ge=1, le=365)
    webhook_retention_days: int = Field(default=7, ge=1, le=30)
    backup_retention_count: int = Field(default=10, ge=1, le=100)
    
    @field_validator('datadir', mode='before')
    def parse_datadir(cls, v):
        if isinstance(v, str):
            return Path(v)
        return v


class LLMConfig(BaseModel):
    """LLM 配置"""
    primary_provider: Literal["ollama", "openclaw"] = "ollama"
    fallback_provider: Literal["ollama", "openclaw", "none"] = "openclaw"
    
    # Ollama 配置
    ollama_host: str = "http://localhost:11434"
    ollama_model_intent: str = "qwen3:8b"
    ollama_model_code: str = "qwen3-coder:30b"
    ollama_model_answer: str = "qwen3-coder:14b"
    ollama_timeout: int = Field(default=300, ge=10, le=600)
    ollama_max_concurrent: int = Field(default=1, ge=1, le=10)
    ollama_embedding_model: str = "nomic-embed-text"
    
    # OpenClaw 配置
    openclaw_enabled: bool = True
    openclaw_url: str = "http://localhost:3000"
    openclaw_timeout: int = Field(default=60, ge=10, le=300)
    openclaw_trigger_failure_count: int = Field(default=5, ge=1, le=20)
    
    @field_validator('ollama_host', 'openclaw_url')
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError(f"URL must start with http:// or https://: {v}")
        return v


class QueueConfig(BaseModel):
    """队列配置"""
    redis_url: str = "redis://localhost:6379/0"
    workers: int = Field(default=4, ge=1, le=20)
    rate_limit_per_minute: int = Field(default=10, ge=1, le=1000)
    max_queue_size: int = Field(default=1000, ge=100, le=10000)
    default_priority: int = Field(default=0, ge=0, le=10)
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay: float = Field(default=1.0, ge=0.1, le=60.0)
    
    @field_validator('redis_url')
    def validate_redis_url(cls, v):
        if not v.startswith('redis://'):
            raise ValueError(f"Redis URL must start with redis://: {v}")
        return v


class NotificationConfig(BaseModel):
    """通知配置"""
    smtp_host: str = "smtp.gmail.com"
    smtp_port: int = Field(default=587, ge=1, le=65535)
    smtp_user: Optional[str] = None
    smtp_password: Optional[str] = None
    smtp_use_tls: bool = True
    admin_email: Optional[str] = None
    
    # 通知触发条件
    notify_admin_on_failure: bool = True
    notify_queue_threshold_seconds: int = Field(default=300, ge=60, le=3600)
    
    @property
    def email_enabled(self) -> bool:
        return all([self.smtp_user, self.smtp_password, self.admin_email])
    
    @field_validator('admin_email', 'smtp_user')
    def validate_email(cls, v):
        if v is None:
            return v
        # 简单邮箱验证
        if '@' not in v:
            raise ValueError(f"Invalid email address: {v}")
        return v


class GitHubConfig(BaseModel):
    """GitHub 配置"""
    app_id: Optional[str] = None
    private_key_path: Optional[str] = None
    webhook_secret: Optional[str] = None
    token: Optional[str] = None
    
    @model_validator(mode='after')
    def load_from_env(self):
        """从环境变量加载 GitHub 配置（支持无前缀的变量名）"""
        if not self.app_id:
            self.app_id = os.getenv('GITHUB_APP_ID')
        if not self.private_key_path:
            self.private_key_path = os.getenv('GITHUB_APP_PRIVATE_KEY_PATH')
        if not self.webhook_secret:
            self.webhook_secret = os.getenv('GITHUB_WEBHOOK_SECRET')
        if not self.token:
            self.token = os.getenv('GITHUB_TOKEN')
        return self
    
    # 触发模式
    issue_trigger_mode: Literal["all", "smart", "none"] = "smart"
    comment_trigger_mode: Literal["all", "smart", "none"] = "smart"
    
    # 限流
    max_file_size: int = Field(default=1048576, ge=1024, le=10485760)  # 1MB - 10MB
    max_files_per_pr: int = Field(default=10, ge=1, le=100)
    
    # 超时配置
    api_timeout: int = Field(default=30, ge=5, le=120)
    api_max_retries: int = Field(default=3, ge=0, le=10)
    
    @model_validator(mode='after')
    def validate_auth(self):
        app_id = self.app_id
        token = self.token
        
        if not app_id and not token:
            # 警告：没有认证信息，但不是错误（可能用于测试）
            pass
        
        return self


class ProcessingConfig(BaseModel):
    """处理配置"""
    # 确认模式
    confirm_mode: Literal["auto", "manual", "smart"] = "auto"
    auto_confirm_threshold: float = Field(default=0.8, ge=0.0, le=1.0)
    
    # Issue 跟踪
    issue_tracking_enabled: bool = True
    max_comment_history: int = Field(default=100, ge=10, le=1000)
    
    # 重试
    max_retries: int = Field(default=3, ge=0, le=10)
    retry_delay: float = Field(default=1.0, ge=0.1, le=60.0)
    retry_backoff: float = Field(default=2.0, ge=1.0, le=5.0)
    
    # 处理超时
    processing_timeout: int = Field(default=600, ge=60, le=3600)  # 10分钟
    
    @field_validator('auto_confirm_threshold')
    def validate_threshold(cls, v):
        if not 0 <= v <= 1:
            raise ValueError(f"Threshold must be between 0 and 1: {v}")
        return v


class LoggingConfig(BaseModel):
    """日志配置"""
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    format: Literal["json", "text"] = "json"
    console_output: bool = True
    file_output: bool = True
    
    # 文件日志开关
    json_file: bool = True   # 输出 JSON 格式日志文件
    text_file: bool = True   # 输出文本格式日志文件
    
    # 调试模式
    debug: bool = False
    trace: bool = False
    
    # 日志轮转
    max_bytes: int = Field(default=100 * 1024 * 1024, ge=1024 * 1024)  # 100MB
    backup_count: int = Field(default=10, ge=1, le=100)


class KnowledgeBaseConfig(BaseModel):
    """知识库配置"""
    enabled: bool = True
    service_url: str = "http://localhost:8000"
    embedding_model: str = "nomic-embed-text"
    embedding_host: str = "http://localhost:11434"
    chroma_dir: Optional[str] = None
    
    @field_validator('service_url', 'embedding_host')
    def validate_url(cls, v):
        if not v.startswith(('http://', 'https://')):
            raise ValueError(f"URL must start with http:// or https://: {v}")
        return v


class WebhookConfig(BaseModel):
    """Webhook 服务器配置"""
    host: str = "0.0.0.0"
    port: int = Field(default=8000, ge=1024, le=65535)
    
    @property
    def url(self) -> str:
        """生成 Webhook URL"""
        return f"http://{self.host}:{self.port}"


# =============================================================================
# 主配置类
# =============================================================================

class AgentConfig(BaseSettings):
    """
    GitHub Agent V3 主配置类
    
    支持：
    1. 环境变量（优先级最高）
    2. 配置文件
    3. 默认值（优先级最低）
    """
    
    # 子配置
    storage: StorageConfig = Field(default_factory=StorageConfig)
    llm: LLMConfig = Field(default_factory=LLMConfig)
    queue: QueueConfig = Field(default_factory=QueueConfig)
    notification: NotificationConfig = Field(default_factory=NotificationConfig)
    github: GitHubConfig = Field(default_factory=GitHubConfig)
    processing: ProcessingConfig = Field(default_factory=ProcessingConfig)
    logging: LoggingConfig = Field(default_factory=LoggingConfig)
    knowledge_base: KnowledgeBaseConfig = Field(default_factory=KnowledgeBaseConfig)
    webhook: WebhookConfig = Field(default_factory=WebhookConfig)
    
    model_config = ConfigDict(
        env_prefix="GITHUB_AGENT_",
        env_nested_delimiter="__",
        case_sensitive=False,
        extra='ignore',
        env_file='.env',
        env_file_encoding='utf-8'
    )
    
    def validate_all(self) -> List[str]:
        """
        验证所有配置，返回错误列表
        
        Returns:
            错误信息列表，空列表表示验证通过
        """
        errors = []
        
        # 验证 GitHub 配置
        if not self.github.app_id and not self.github.token:
            errors.append("Missing GitHub authentication: either app_id or token must be provided")
        
        if self.github.app_id and not self.github.private_key_path:
            errors.append("GitHub App private_key_path is required when using app_id")
        
        if self.github.private_key_path:
            key_path = Path(self.github.private_key_path)
            if not key_path.exists():
                errors.append(f"GitHub private key not found: {self.github.private_key_path}")
        
        if not self.github.webhook_secret:
            errors.append("Missing GitHub webhook_secret (required for security)")
        
        # 验证存储目录可写
        try:
            self.storage.datadir.mkdir(parents=True, exist_ok=True)
            test_file = self.storage.datadir / ".write_test"
            test_file.touch()
            test_file.unlink()
        except Exception as e:
            errors.append(f"Storage directory is not writable: {self.storage.datadir} ({e})")
        
        # 验证 LLM 配置
        if self.llm.primary_provider == "ollama" and not self.llm.ollama_host:
            errors.append("Ollama host is required when using ollama provider")
        
        return errors
    
    def to_dict(self, hide_secrets: bool = True) -> Dict[str, Any]:
        """
        导出为字典
        
        Args:
            hide_secrets: 是否隐藏敏感信息
        
        Returns:
            配置字典
        """
        data = self.dict()
        
        if hide_secrets:
            # 隐藏敏感字段
            if "github" in data and "token" in data["github"]:
                token = data["github"]["token"]
                if token:
                    data["github"]["token"] = "***" + token[-4:] if len(token) > 4 else "***"
            
            if "notification" in data:
                if "smtp_password" in data["notification"]:
                    data["notification"]["smtp_password"] = "***"
        
        return data
    
    def save_to_file(self, path: Optional[Path] = None):
        """
        保存配置到 YAML 文件
        
        Args:
            path: 配置文件路径，默认使用 datadir/config/agent.yml
        """
        if path is None:
            path = self.storage.datadir / "config" / "agent.yml"
        
        path.parent.mkdir(parents=True, exist_ok=True)
        
        # 转换为字典并保存
        data = self.to_dict(hide_secrets=False)
        
        # 转换 Path 对象为字符串
        def convert_paths(obj):
            if isinstance(obj, dict):
                return {k: convert_paths(v) for k, v in obj.items()}
            elif isinstance(obj, list):
                return [convert_paths(i) for i in obj]
            elif isinstance(obj, Path):
                return str(obj)
            return obj
        
        data = convert_paths(data)
        
        with open(path, 'w', encoding='utf-8') as f:
            yaml.dump(data, f, default_flow_style=False, allow_unicode=True, sort_keys=False)


# =============================================================================
# 配置加载器
# =============================================================================

class ConfigLoader:
    """配置加载器"""
    
    @staticmethod
    def from_file(path: Path) -> AgentConfig:
        """从 YAML 文件加载配置"""
        if not path.exists():
            raise ConfigError(f"Config file not found: {path}")
        
        try:
            with open(path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f) or {}
            
            return AgentConfig(**data)
        except yaml.YAMLError as e:
            raise ConfigError(f"Invalid YAML in config file: {e}")
        except Exception as e:
            raise ConfigError(f"Failed to load config: {e}")
    
    @staticmethod
    def from_env() -> AgentConfig:
        """从环境变量加载配置"""
        return AgentConfig()
    
    @staticmethod
    def load(
        config_file: Optional[Path] = None,
        datadir: Optional[Path] = None
    ) -> AgentConfig:
        """
        加载配置（综合方式）
        
        优先级：
        1. 环境变量
        2. 配置文件
        3. 默认值
        
        Args:
            config_file: 配置文件路径
            datadir: 数据目录（用于确定默认配置文件位置）
        
        Returns:
            AgentConfig 实例
        """
        # 1. 从文件加载（如果存在）
        if config_file and config_file.exists():
            config = ConfigLoader.from_file(config_file)
        elif datadir:
            default_path = datadir / "config" / "agent.yml"
            if default_path.exists():
                config = ConfigLoader.from_file(default_path)
            else:
                config = AgentConfig()
        else:
            config = AgentConfig()
        
        # 2. 环境变量会自动覆盖（通过 Pydantic BaseSettings）
        
        return config


# =============================================================================
# 全局单例（向后兼容）
# =============================================================================

_config_instance: Optional[AgentConfig] = None


def get_config(
    storage_dir: Optional[Path] = None,
    reload: bool = False
) -> AgentConfig:
    """
    获取 ConfigManager 单例（向后兼容）
    
    Args:
        storage_dir: 数据目录（覆盖配置中的值）
        reload: 是否强制重新加载
    
    Returns:
        AgentConfig 实例
    """
    global _config_instance
    
    if _config_instance is None or reload:
        if storage_dir is not None:
            # 使用指定的数据目录
            _config_instance = ConfigLoader.load(datadir=storage_dir)
        else:
            # 从环境变量/配置文件加载（Pydantic Settings 自动处理 .env）
            _config_instance = AgentConfig()
    
    return _config_instance


def reset_config():
    """重置配置单例（主要用于测试）"""
    global _config_instance
    _config_instance = None
