"""
GitHub Agent V3 统一异常处理体系

所有模块的自定义异常定义
"""

from typing import Optional, Any
from enum import Enum


class ErrorCode(Enum):
    """错误代码枚举"""
    # 系统级错误
    UNKNOWN_ERROR = "E0000"
    CONFIG_ERROR = "E0001"
    VALIDATION_ERROR = "E0002"
    
    # GitHub API 错误
    GITHUB_API_ERROR = "E1000"
    GITHUB_AUTH_ERROR = "E1001"
    GITHUB_RATE_LIMIT = "E1002"
    GITHUB_NOT_FOUND = "E1003"
    
    # LLM 服务错误
    LLM_PROVIDER_ERROR = "E2000"
    LLM_TIMEOUT_ERROR = "E2001"
    LLM_RATE_LIMIT = "E2002"
    LLM_CONTENT_FILTER = "E2003"
    
    # 队列错误
    QUEUE_ERROR = "E3000"
    QUEUE_FULL = "E3001"
    QUEUE_TIMEOUT = "E3002"
    
    # 存储错误
    STORAGE_ERROR = "E4000"
    STORAGE_NOT_FOUND = "E4001"
    STORAGE_IO_ERROR = "E4002"
    
    # 知识库错误
    KB_ERROR = "E5000"
    KB_NOT_FOUND = "E5001"
    KB_INDEX_ERROR = "E5002"


class GitHubAgentException(Exception):
    """
    基础异常类
    
    所有自定义异常的基类，提供统一的错误处理接口
    """
    
    def __init__(
        self,
        message: str,
        code: ErrorCode = ErrorCode.UNKNOWN_ERROR,
        details: Optional[dict] = None,
        original_error: Optional[Exception] = None
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.details = details or {}
        self.original_error = original_error
    
    def to_dict(self) -> dict:
        """转换为字典格式（用于 API 响应）"""
        result = {
            "error": True,
            "code": self.code.value,
            "message": self.message,
        }
        if self.details:
            result["details"] = self.details
        return result
    
    def __str__(self) -> str:
        if self.original_error:
            return f"[{self.code.value}] {self.message} (caused by: {self.original_error})"
        return f"[{self.code.value}] {self.message}"


# =============================================================================
# 配置相关异常
# =============================================================================

class ConfigError(GitHubAgentException):
    """配置错误"""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.CONFIG_ERROR,
            details=details
        )


class ValidationError(GitHubAgentException):
    """数据验证错误"""
    
    def __init__(self, message: str, field: Optional[str] = None, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.VALIDATION_ERROR,
            details={"field": field, **(details or {})}
        )


# =============================================================================
# GitHub API 相关异常
# =============================================================================

class GitHubAPIError(GitHubAgentException):
    """GitHub API 错误基类"""
    
    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_body: Optional[str] = None,
        details: Optional[dict] = None
    ):
        self.status_code = status_code
        self.response_body = response_body
        
        # 根据状态码确定错误码
        code = ErrorCode.GITHUB_API_ERROR
        if status_code == 401:
            code = ErrorCode.GITHUB_AUTH_ERROR
        elif status_code == 404:
            code = ErrorCode.GITHUB_NOT_FOUND
        elif status_code == 429:
            code = ErrorCode.GITHUB_RATE_LIMIT
        
        super().__init__(
            message=message,
            code=code,
            details={
                "status_code": status_code,
                "response_body": response_body,
                **(details or {})
            }
        )


class GitHubAuthError(GitHubAPIError):
    """GitHub 认证错误"""
    
    def __init__(self, message: str = "GitHub authentication failed", details: Optional[dict] = None):
        super().__init__(
            message=message,
            status_code=401,
            details=details
        )


class GitHubRateLimitError(GitHubAPIError):
    """GitHub 速率限制错误"""
    
    def __init__(
        self,
        message: str = "GitHub API rate limit exceeded",
        reset_at: Optional[int] = None,
        details: Optional[dict] = None
    ):
        self.reset_at = reset_at
        super().__init__(
            message=message,
            status_code=429,
            details={
                "reset_at": reset_at,
                **(details or {})
            }
        )


class GitHubNotFoundError(GitHubAPIError):
    """GitHub 资源不存在"""
    
    def __init__(self, resource: str, details: Optional[dict] = None):
        super().__init__(
            message=f"Resource not found: {resource}",
            status_code=404,
            details={"resource": resource, **(details or {})}
        )


# =============================================================================
# LLM 服务相关异常
# =============================================================================

class LLMProviderError(GitHubAgentException):
    """LLM 提供商错误基类"""
    
    def __init__(
        self,
        message: str,
        provider: Optional[str] = None,
        details: Optional[dict] = None,
        original_error: Optional[Exception] = None
    ):
        self.provider = provider
        super().__init__(
            message=message,
            code=ErrorCode.LLM_PROVIDER_ERROR,
            details={"provider": provider, **(details or {})},
            original_error=original_error
        )


class LLMTimeoutError(LLMProviderError):
    """LLM 调用超时"""
    
    def __init__(
        self,
        provider: str,
        timeout: float,
        details: Optional[dict] = None
    ):
        super().__init__(
            message=f"LLM request to {provider} timed out after {timeout}s",
            provider=provider,
            details={"timeout": timeout, **(details or {})}
        )
        self.code = ErrorCode.LLM_TIMEOUT_ERROR


class LLMRateLimitError(LLMProviderError):
    """LLM 速率限制"""
    
    def __init__(
        self,
        provider: str,
        retry_after: Optional[int] = None,
        details: Optional[dict] = None
    ):
        super().__init__(
            message=f"Rate limit exceeded for {provider}",
            provider=provider,
            details={"retry_after": retry_after, **(details or {})}
        )
        self.code = ErrorCode.LLM_RATE_LIMIT


class LLMContentFilterError(LLMProviderError):
    """LLM 内容被过滤"""
    
    def __init__(self, provider: str, reason: Optional[str] = None):
        super().__init__(
            message=f"Content filtered by {provider}",
            provider=provider,
            details={"reason": reason}
        )
        self.code = ErrorCode.LLM_CONTENT_FILTER


# =============================================================================
# 队列相关异常
# =============================================================================

class QueueError(GitHubAgentException):
    """队列错误基类"""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.QUEUE_ERROR,
            details=details
        )


class QueueFullError(QueueError):
    """队列已满"""
    
    def __init__(self, max_size: int, current_size: int):
        super().__init__(
            message=f"Queue is full ({current_size}/{max_size})",
            details={"max_size": max_size, "current_size": current_size}
        )
        self.code = ErrorCode.QUEUE_FULL


class QueueTimeoutError(QueueError):
    """队列操作超时"""
    
    def __init__(self, operation: str, timeout: float):
        super().__init__(
            message=f"Queue operation '{operation}' timed out",
            details={"operation": operation, "timeout": timeout}
        )
        self.code = ErrorCode.QUEUE_TIMEOUT


# =============================================================================
# 存储相关异常
# =============================================================================

class StorageError(GitHubAgentException):
    """存储错误基类"""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.STORAGE_ERROR,
            details=details
        )


class StorageNotFoundError(StorageError):
    """存储资源不存在"""
    
    def __init__(self, path: str, details: Optional[dict] = None):
        super().__init__(
            message=f"Storage resource not found: {path}",
            details={"path": path, **(details or {})}
        )
        self.code = ErrorCode.STORAGE_NOT_FOUND


class StorageIOError(StorageError):
    """存储 I/O 错误"""
    
    def __init__(self, message: str, path: Optional[str] = None, original_error: Optional[Exception] = None):
        super().__init__(
            message=message,
            details={"path": path},
            original_error=original_error
        )
        self.code = ErrorCode.STORAGE_IO_ERROR


# =============================================================================
# 知识库相关异常
# =============================================================================

class KnowledgeBaseError(GitHubAgentException):
    """知识库错误基类"""
    
    def __init__(self, message: str, details: Optional[dict] = None):
        super().__init__(
            message=message,
            code=ErrorCode.KB_ERROR,
            details=details
        )


class KnowledgeBaseNotFoundError(KnowledgeBaseError):
    """知识库资源不存在"""
    
    def __init__(self, resource: str, details: Optional[dict] = None):
        super().__init__(
            message=f"Knowledge base resource not found: {resource}",
            details={"resource": resource, **(details or {})}
        )
        self.code = ErrorCode.KB_NOT_FOUND


class KnowledgeBaseIndexError(KnowledgeBaseError):
    """知识库索引错误"""
    
    def __init__(self, message: str, document: Optional[str] = None):
        super().__init__(
            message=message,
            details={"document": document}
        )
        self.code = ErrorCode.KB_INDEX_ERROR


# =============================================================================
# 异常处理工具函数
# =============================================================================

def handle_exception(exc: Exception) -> GitHubAgentException:
    """
    将标准异常转换为 GitHubAgentException
    
    用于统一处理未知异常
    """
    if isinstance(exc, GitHubAgentException):
        return exc
    
    # 处理 requests 异常
    if exc.__class__.__name__ == "HTTPError":
        status_code = getattr(exc.response, "status_code", None) if hasattr(exc, "response") else None
        return GitHubAPIError(
            message=str(exc),
            status_code=status_code,
            original_error=exc
        )
    
    if exc.__class__.__name__ == "ConnectionError":
        return GitHubAPIError(
            message=f"Connection error: {exc}",
            original_error=exc
        )
    
    if exc.__class__.__name__ == "Timeout":
        return LLMTimeoutError(
            provider="unknown",
            timeout=0,
            original_error=exc
        )
    
    # 默认转换
    return GitHubAgentException(
        message=f"Unexpected error: {exc}",
        code=ErrorCode.UNKNOWN_ERROR,
        original_error=exc
    )
