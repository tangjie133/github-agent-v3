"""
统一结构化日志系统
- 全项目统一使用
- 支持链路追踪
- 多目标输出（控制台、文件、JSON）
"""

import sys
import json
import time
import functools
import logging
import logging.handlers
from pathlib import Path
from typing import Dict, Any, Optional, Callable
from contextvars import ContextVar
from dataclasses import dataclass
import datetime
from core.utils import utc_now_iso

# 请求上下文（自动传递）
request_ctx: ContextVar[Dict[str, Any]] = ContextVar('request_ctx', default={})

# Logger 缓存
_logger_cache: Dict[str, 'StructuredLogger'] = {}


@dataclass
class LogEntry:
    """日志条目"""
    timestamp: str
    level: str
    logger: str
    event: str
    message: Optional[str] = None
    extra: Dict[str, Any] = None
    trace_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        data = {
            'timestamp': self.timestamp,
            'level': self.level,
            'logger': self.logger,
            'event': self.event,
        }
        if self.message:
            data['message'] = self.message
        if self.extra:
            data.update(self.extra)
        if self.trace_id:
            data['trace_id'] = self.trace_id
        return data


class StructuredLogger:
    """
    结构化日志器
    
    用法：
        logger = get_logger(__name__)
        logger.info("event.name", key=value)
    """
    
    def __init__(self, name: str):
        self.name = name
        self._logger = logging.getLogger(name)
    
    def _log(self, level: str, event: str, **kwargs):
        """统一日志输出"""
        # 获取上下文
        context = request_ctx.get()
        
        # 创建日志条目
        entry = LogEntry(
            timestamp=utc_now_iso(),
            level=level.upper(),
            logger=self.name,
            event=event,
            extra={**context, **kwargs},
            trace_id=context.get('trace_id'),
        )
        
        # 输出到标准库 logger
        extra = entry.to_dict()
        extra.pop('timestamp', None)  # 避免重复
        extra.pop('level', None)
        extra.pop('logger', None)
        
        self._logger.log(
            getattr(logging, level.upper()),
            json.dumps(entry.to_dict(), ensure_ascii=False),
            extra={'structured': extra}
        )
    
    def bind(self, **kwargs) -> 'StructuredLogger':
        """绑定上下文"""
        new_logger = StructuredLogger(self.name)
        # 复制当前上下文并添加新值
        current = request_ctx.get().copy()
        current.update(kwargs)
        new_logger._context = current
        return new_logger
    
    def debug(self, event: str, **kwargs):
        self._log('debug', event, **kwargs)
    
    def info(self, event: str, **kwargs):
        self._log('info', event, **kwargs)
    
    def warning(self, event: str, **kwargs):
        self._log('warning', event, **kwargs)
    
    def error(self, event: str, **kwargs):
        self._log('error', event, **kwargs)
    
    def exception(self, event: str, **kwargs):
        """记录异常（自动包含堆栈）"""
        self._log('error', event, **kwargs)


def get_logger(name: str) -> StructuredLogger:
    """获取模块级 logger"""
    if name not in _logger_cache:
        _logger_cache[name] = StructuredLogger(name)
    return _logger_cache[name]


class ContextBinder:
    """上下文绑定上下文管理器"""
    
    def __init__(self, **kwargs):
        self.kwargs = kwargs
        self.token = None
    
    def __enter__(self):
        current = request_ctx.get().copy()
        current.update(self.kwargs)
        self.token = request_ctx.set(current)
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.token:
            request_ctx.reset(self.token)


def bind_context(**kwargs):
    """创建上下文绑定器"""
    return ContextBinder(**kwargs)


def traced(event_name: Optional[str] = None, 
          log_args: bool = False,
          log_result: bool = False):
    """
    函数追踪装饰器
    
    自动记录：
    - 函数入口
    - 执行时间
    - 成功/失败
    - 异常信息
    """
    def decorator(func: Callable) -> Callable:
        logger = get_logger(func.__module__)
        name = event_name or func.__name__
        
        is_async = hasattr(func, '__code__') and func.__code__.co_flags & 0x80
        
        @functools.wraps(func)
        async def async_wrapper(*args, **kwargs):
            args_info = {}
            if log_args:
                args_info = {
                    'args_count': len(args),
                    'kwargs_keys': list(kwargs.keys())
                }
            
            logger.info(f"{name}.started", **args_info)
            start_time = time.time()
            
            try:
                result = await func(*args, **kwargs)
                
                result_info = {}
                if log_result and result is not None:
                    result_info['result_type'] = type(result).__name__
                
                logger.info(f"{name}.completed",
                          duration_ms=(time.time() - start_time) * 1000,
                          **result_info)
                return result
                
            except Exception as e:
                logger.error(f"{name}.failed",
                           duration_ms=(time.time() - start_time) * 1000,
                           error_type=type(e).__name__,
                           error_message=str(e))
                raise
        
        @functools.wraps(func)
        def sync_wrapper(*args, **kwargs):
            args_info = {}
            if log_args:
                args_info = {
                    'args_count': len(args),
                    'kwargs_keys': list(kwargs.keys())
                }
            
            logger.info(f"{name}.started", **args_info)
            start_time = time.time()
            
            try:
                result = func(*args, **kwargs)
                
                result_info = {}
                if log_result and result is not None:
                    result_info['result_type'] = type(result).__name__
                
                logger.info(f"{name}.completed",
                          duration_ms=(time.time() - start_time) * 1000,
                          **result_info)
                return result
                
            except Exception as e:
                logger.error(f"{name}.failed",
                           duration_ms=(time.time() - start_time) * 1000,
                           error_type=type(e).__name__,
                           error_message=str(e))
                raise
        
        return async_wrapper if is_async else sync_wrapper
    
    return decorator


# ========== 格式化器 ==========

class JsonFormatter(logging.Formatter):
    """JSON 格式日志"""
    
    def format(self, record: logging.LogRecord) -> str:
        try:
            # 尝试解析已结构化的数据
            data = json.loads(record.getMessage())
        except json.JSONDecodeError:
            # 普通文本，包装成结构化格式
            data = {
                'timestamp': datetime.datetime.utcnow().isoformat() + 'Z',
                'level': record.levelname,
                'logger': record.name,
                'event': 'log.message',
                'message': record.getMessage(),
            }
            if hasattr(record, 'structured'):
                data.update(record.structured)
        
        return json.dumps(data, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    """人类可读的文本格式"""
    
    def format(self, record: logging.LogRecord) -> str:
        try:
            data = json.loads(record.getMessage())
            # 简化格式
            timestamp = data.get('timestamp', '')
            level = data.get('level', 'INFO')
            event = data.get('event', '')
            extra = {k: v for k, v in data.items() 
                    if k not in ('timestamp', 'level', 'logger', 'event')}
            
            extra_str = ' '.join(f"{k}={v}" for k, v in extra.items()) if extra else ''
            return f"[{timestamp}] {level:8} {event:40} {extra_str}"
        except json.JSONDecodeError:
            timestamp = getattr(record, 'asctime', None) or datetime.datetime.fromtimestamp(record.created).strftime('%Y-%m-%dT%H:%M:%S')
            return f"[{timestamp}] {record.levelname:8} {record.getMessage()}"


class ColoredFormatter(TextFormatter):
    """带颜色的控制台输出"""
    
    COLORS = {
        'DEBUG': '\033[36m',     # Cyan
        'INFO': '\033[32m',      # Green
        'WARNING': '\033[33m',   # Yellow
        'ERROR': '\033[31m',     # Red
        'CRITICAL': '\033[35m',  # Magenta
        'RESET': '\033[0m',
    }
    
    def format(self, record: logging.LogRecord) -> str:
        formatted = super().format(record)
        level = record.levelname
        color = self.COLORS.get(level, self.COLORS['RESET'])
        reset = self.COLORS['RESET']
        return f"{color}{formatted}{reset}"


# ========== 初始化 ==========

def setup_logging(logs_dir: Path, 
                 level: str = 'INFO',
                 console: bool = True,
                 json_file: bool = False,  # 默认禁用文件日志，简化启动
                 text_file: bool = False):
    """
    配置日志系统
    
    Args:
        logs_dir: 日志目录
        level: 日志级别
        console: 是否输出到控制台
        json_file: 是否输出 JSON 文件
        text_file: 是否输出文本文件
    """
    logs_dir = Path(logs_dir)
    
    # 创建日志目录
    if json_file or text_file:
        (logs_dir / 'agent').mkdir(parents=True, exist_ok=True)
    logs_dir.mkdir(parents=True, exist_ok=True)
    
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, level.upper()))
    
    # 清除现有处理器
    root_logger.handlers = []
    
    handlers = []
    
    # 1. 控制台输出（带颜色）
    if console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setFormatter(ColoredFormatter())
        handlers.append(console_handler)
    
    # 2. JSON 文件（机器解析）
    if json_file:
        json_handler = logging.handlers.RotatingFileHandler(
            logs_dir / 'agent' / 'current.json',
            maxBytes=100 * 1024 * 1024,  # 100MB
            backupCount=10
        )
        json_handler.setFormatter(JsonFormatter())
        handlers.append(json_handler)
    
    # 3. 文本文件（人工阅读）
    if text_file:
        text_handler = logging.handlers.RotatingFileHandler(
            logs_dir / 'agent' / 'current.log',
            maxBytes=100 * 1024 * 1024,
            backupCount=10
        )
        text_handler.setFormatter(TextFormatter())
        handlers.append(text_handler)
    
    # 4. 错误日志单独文件
    if text_file:
        error_handler = logging.handlers.RotatingFileHandler(
            logs_dir / 'agent' / 'error.log',
            maxBytes=50 * 1024 * 1024,
            backupCount=5
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(TextFormatter())
        handlers.append(error_handler)
    
    # 添加所有处理器
    for handler in handlers:
        root_logger.addHandler(handler)
    
    # 设置第三方库日志级别
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('asyncio').setLevel(logging.WARNING)
    
    # 获取 logger 并记录启动
    logger = get_logger('logging')
    logger.info('logging.initialized',
               logs_dir=str(logs_dir),
               log_level=level,
               handlers=[h.__class__.__name__ for h in handlers])


def set_trace_id(trace_id: str):
    """设置当前请求的 trace_id"""
    current = request_ctx.get().copy()
    current['trace_id'] = trace_id
    request_ctx.set(current)


def get_trace_id() -> Optional[str]:
    """获取当前 trace_id"""
    return request_ctx.get().get('trace_id')
