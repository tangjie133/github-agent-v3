"""
调试配置模块
提供调试模式开关和详细日志控制
"""

import os
import sys
import json
import functools
import time
from dataclasses import dataclass, field, asdict
from typing import Dict, Any, Optional, Callable
from datetime import datetime
from pathlib import Path

from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DebugConfig:
    """调试配置类
    
    环境变量控制：
    - AGENT_DEBUG: 启用调试模式 (true/false)
    - AGENT_DEBUG_LEVEL: 调试级别 (basic/detailed/trace)
    - AGENT_DRY_RUN: 模拟模式，不实际调用 API (true/false)
    - AGENT_LOG_STEPS: 记录每个处理步骤 (true/false)
    - AGENT_SAVE_CONTEXT: 保存处理上下文 (true/false)
    - AGENT_PERF_TRACK: 性能追踪 (true/false)
    """
    
    # 主开关
    enabled: bool = field(default_factory=lambda: os.getenv("AGENT_DEBUG", "false").lower() == "true")
    
    # 调试级别: basic, detailed, trace
    level: str = field(default_factory=lambda: os.getenv("AGENT_DEBUG_LEVEL", "basic"))
    
    # 模拟模式（不实际调用 GitHub API）
    dry_run: bool = field(default_factory=lambda: os.getenv("AGENT_DRY_RUN", "false").lower() == "true")
    
    # 详细日志开关
    log_steps: bool = field(default_factory=lambda: os.getenv("AGENT_LOG_STEPS", "true").lower() == "true")
    log_state_changes: bool = True
    log_api_calls: bool = True
    log_decisions: bool = True
    
    # 性能追踪
    perf_track: bool = field(default_factory=lambda: os.getenv("AGENT_PERF_TRACK", "true").lower() == "true")
    perf_slow_threshold_ms: int = 1000  # 慢操作阈值
    
    # 上下文保存
    save_context: bool = field(default_factory=lambda: os.getenv("AGENT_SAVE_CONTEXT", "false").lower() == "true")
    context_save_path: str = "/home/tj/state/debug"
    
    # 跟踪 ID 生成
    generate_trace_id: bool = True
    
    # 控制台彩色输出
    color_output: bool = True
    
    def __post_init__(self):
        """初始化后处理"""
        if self.enabled:
            # 确保调试目录存在
            if self.save_context:
                Path(self.context_save_path).mkdir(parents=True, exist_ok=True)
            
            # 打印调试配置
            self._print_config()
    
    def _print_config(self):
        """打印调试配置"""
        config_str = json.dumps(asdict(self), indent=2, default=str)
        logger.info("Debug mode enabled")
        logger.info(f"Config: {config_str}")
    
    def is_basic(self) -> bool:
        """是否为基本调试级别"""
        return self.enabled and self.level in ["basic", "detailed", "trace"]
    
    def is_detailed(self) -> bool:
        """是否为详细调试级别"""
        return self.enabled and self.level in ["detailed", "trace"]
    
    def is_trace(self) -> bool:
        """是否为追踪调试级别"""
        return self.enabled and self.level == "trace"
    
    def should_log_step(self, step_name: str) -> bool:
        """是否应该记录该步骤"""
        if not self.enabled or not self.log_steps:
            return False
        
        # trace 级别记录所有步骤
        if self.is_trace():
            return True
        
        # detailed 级别只记录关键步骤
        if self.is_detailed():
            key_steps = ["trigger", "intent", "decision", "execute", "pr_create"]
            return any(key in step_name.lower() for key in key_steps)
        
        # basic 级别只记录执行步骤
        return "execute" in step_name.lower() or "pr" in step_name.lower()


# 全局配置实例
debug_config = DebugConfig()


class Colors:
    """终端颜色"""
    RESET = "\033[0m"
    BOLD = "\033[1m"
    
    # 前景色
    BLACK = "\033[30m"
    RED = "\033[31m"
    GREEN = "\033[32m"
    YELLOW = "\033[33m"
    BLUE = "\033[34m"
    MAGENTA = "\033[35m"
    CYAN = "\033[36m"
    WHITE = "\033[37m"
    
    # 背景色
    BG_RED = "\033[41m"
    BG_GREEN = "\033[42m"
    BG_YELLOW = "\033[43m"
    BG_BLUE = "\033[44m"


def colorize(text: str, color: str, bold: bool = False) -> str:
    """添加颜色"""
    if not debug_config.color_output or not sys.stdout.isatty():
        return text
    
    color_code = getattr(Colors, color.upper(), "")
    bold_code = Colors.BOLD if bold else ""
    return f"{bold_code}{color_code}{text}{Colors.RESET}"


class DebugLogger:
    """调试日志记录器"""
    
    def __init__(self, trace_id: Optional[str] = None):
        self.trace_id = trace_id or self._generate_trace_id()
        self.step_count = 0
    
    @staticmethod
    def _generate_trace_id() -> str:
        """生成跟踪 ID"""
        import uuid
        return str(uuid.uuid4())[:8]
    
    def _log(self, level: str, emoji: str, message: str, **kwargs):
        """内部日志方法"""
        if not debug_config.enabled:
            return
        
        self.step_count += 1
        timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        
        # 构建日志消息
        log_parts = [
            f"[{timestamp}]",
            f"[{self.trace_id}]",
            f"{emoji}",
            message
        ]
        
        if kwargs:
            # 格式化额外数据
            data_str = json.dumps(kwargs, default=str, ensure_ascii=False)
            if len(data_str) > 200:
                data_str = data_str[:200] + "..."
            log_parts.append(data_str)
        
        log_msg = " ".join(log_parts)
        
        # 根据级别使用不同颜色
        if debug_config.color_output:
            if level == "error":
                log_msg = colorize(log_msg, "red", bold=True)
            elif level == "warning":
                log_msg = colorize(log_msg, "yellow")
            elif level == "success":
                log_msg = colorize(log_msg, "green")
            elif level == "info":
                log_msg = colorize(log_msg, "cyan")
        
        # 输出到控制台
        print(log_msg)
        
        # 同时记录到日志
        log_func = getattr(logger, level if level != "success" else "info")
        log_func(log_msg)
    
    def step(self, name: str, **kwargs):
        """记录步骤开始"""
        if debug_config.should_log_step(name):
            self._log("info", "▶️", f"STEP: {name}", **kwargs)
    
    def step_end(self, name: str, status: str = "ok", duration_ms: float = 0, **kwargs):
        """记录步骤结束"""
        if not debug_config.should_log_step(name):
            return
        
        if status == "ok":
            emoji = "✅"
            level = "success"
        elif status == "skip":
            emoji = "⏭️"
            level = "warning"
        elif status == "fail":
            emoji = "❌"
            level = "error"
        else:
            emoji = "⏹️"
            level = "info"
        
        msg = f"STEP END: {name} [{status}]"
        if duration_ms > 0:
            msg += f" ({duration_ms:.2f}ms)"
        
        self._log(level, emoji, msg, **kwargs)
    
    def check(self, name: str, result: bool, details: Dict = None):
        """记录检查结果"""
        if not debug_config.is_detailed():
            return
        
        emoji = "✓" if result else "✗"
        status = "PASS" if result else "FAIL"
        self._log("info" if result else "warning", emoji, f"CHECK: {name} [{status}]", 
                 **(details or {}))
    
    def skip(self, reason: str, **kwargs):
        """记录跳过"""
        self._log("warning", "⏭️", f"SKIP: {reason}", **kwargs)
    
    def error(self, message: str, exception: Exception = None, **kwargs):
        """记录错误"""
        if exception:
            kwargs["exception_type"] = type(exception).__name__
            kwargs["exception_msg"] = str(exception)
        self._log("error", "❌", f"ERROR: {message}", **kwargs)
    
    def api_call(self, api_name: str, **kwargs):
        """记录 API 调用"""
        if debug_config.log_api_calls:
            self._log("info", "🌐", f"API: {api_name}", **kwargs)
    
    def decision(self, decision_type: str, result: Any, **kwargs):
        """记录决策结果"""
        if debug_config.log_decisions:
            kwargs["result"] = str(result)
            self._log("info", "🤔", f"DECISION: {decision_type}", **kwargs)
    
    def state_change(self, from_state: str, to_state: str, **kwargs):
        """记录状态变化"""
        if debug_config.log_state_changes:
            self._log("info", "📝", f"STATE: {from_state} → {to_state}", **kwargs)
    
    def dry_run(self, action: str, **kwargs):
        """记录模拟操作"""
        if debug_config.dry_run:
            self._log("warning", "🧪", f"DRY RUN: {action}", **kwargs)
    
    def summary(self, data: Dict):
        """记录摘要"""
        if not debug_config.enabled:
            return
        
        print(f"\n{'='*60}")
        print(colorize(f"📊 处理摘要 [{self.trace_id}]", "cyan", bold=True))
        print(f"{'='*60}")
        print(json.dumps(data, indent=2, default=str, ensure_ascii=False))
        print(f"{'='*60}\n")
        
        logger.info(f"Summary [{self.trace_id}]: {json.dumps(data, default=str)}")
    
    def save_context(self, context_data: Dict, filename: str = None):
        """保存上下文到文件"""
        if not debug_config.save_context:
            return
        
        try:
            if filename is None:
                filename = f"{self.trace_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
            
            filepath = Path(debug_config.context_save_path) / filename
            filepath.parent.mkdir(parents=True, exist_ok=True)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(context_data, f, indent=2, default=str, ensure_ascii=False)
            
            self._log("info", "💾", f"Context saved: {filepath}")
            
        except Exception as e:
            self.error("Failed to save context", exception=e)


# 性能追踪装饰器
def debug_perf(name: Optional[str] = None):
    """性能追踪装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            if not debug_config.perf_track:
                return func(*args, **kwargs)
            
            func_name = name or func.__name__
            start = time.perf_counter()
            
            try:
                result = func(*args, **kwargs)
                status = "ok"
                return result
            except Exception as e:
                status = f"error:{type(e).__name__}"
                raise
            finally:
                elapsed = (time.perf_counter() - start) * 1000
                
                # 创建临时 logger 输出
                if elapsed > debug_config.perf_slow_threshold_ms:
                    print(colorize(f"🐌 SLOW: {func_name} took {elapsed:.2f}ms [{status}]", "red", bold=True))
                elif debug_config.is_detailed():
                    print(f"⏱️  PERF: {func_name} took {elapsed:.2f}ms [{status}]")
                
                logger.debug(f"PERF: {func_name}={elapsed:.2f}ms")
        
        return wrapper
    return decorator


# 步骤追踪装饰器
def debug_step(step_name: Optional[str] = None):
    """步骤追踪装饰器"""
    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            name = step_name or func.__name__
            
            # 获取或创建 debug_logger
            debug_logger = None
            for arg in args:
                if hasattr(arg, 'debug_logger'):
                    debug_logger = arg.debug_logger
                    break
            
            if debug_logger and debug_config.should_log_step(name):
                debug_logger.step(name)
            
            start = time.perf_counter()
            try:
                result = func(*args, **kwargs)
                status = "ok"
                return result
            except Exception as e:
                status = "fail"
                if debug_logger:
                    debug_logger.error(f"Step {name} failed", exception=e)
                raise
            finally:
                if debug_logger:
                    elapsed = (time.perf_counter() - start) * 1000
                    debug_logger.step_end(name, status, elapsed)
        
        return wrapper
    return decorator


# 快捷函数
def get_debug_logger(trace_id: Optional[str] = None) -> DebugLogger:
    """获取调试日志记录器"""
    return DebugLogger(trace_id)


def is_debug() -> bool:
    """是否处于调试模式"""
    return debug_config.enabled


def is_dry_run() -> bool:
    """是否处于模拟模式"""
    return debug_config.dry_run


def print_banner():
    """打印调试模式横幅"""
    if not debug_config.enabled:
        return
    
    banner = f"""
╔══════════════════════════════════════════════════════════════╗
║  🔧 DEBUG MODE ENABLED                                       ║
║  Level: {debug_config.level:<12}  Dry Run: {str(debug_config.dry_run):<5}               ║
╚══════════════════════════════════════════════════════════════╝
"""
    print(colorize(banner, "yellow", bold=True))
