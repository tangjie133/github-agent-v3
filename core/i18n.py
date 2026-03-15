"""
国际化模块 (i18n)

支持中英文自动检测和切换
"""

import re
from enum import Enum
from typing import Dict, Optional
from dataclasses import dataclass

from core.logging import get_logger

logger = get_logger(__name__)


class Language(Enum):
    """语言枚举"""
    AUTO = "auto"
    ENGLISH = "en"
    CHINESE = "zh"


@dataclass
class I18nString:
    """国际化字符串"""
    en: str
    zh: str
    
    def get(self, lang: str) -> str:
        """获取指定语言的字符串"""
        if lang == "zh":
            return self.zh
        return self.en


# 预设的国际化消息
MESSAGES = {
    # 确认机制消息
    "fix_preview_title": I18nString(
        en="🤖 Fix Preview",
        zh="🤖 修复方案预览"
    ),
    "fix_generated": I18nString(
        en="Fix generated for {file_count} file(s)",
        zh="已为 {file_count} 个文件生成修复方案"
    ),
    "confirm_prompt": I18nString(
        en="Please review the changes and confirm",
        zh="请查看修改并确认"
    ),
    "confirm_button": I18nString(
        en="✅ Confirm Apply",
        zh="✅ 确认应用"
    ),
    "reject_button": I18nString(
        en="❌ Reject",
        zh="❌ 拒绝"
    ),
    "modify_button": I18nString(
        en="💬 Suggest Changes",
        zh="💬 建议修改"
    ),
    "preview_pr_created": I18nString(
        en="Preview PR created: #{pr_number}",
        zh="预览 PR 已创建: #{pr_number}"
    ),
    "timeout_notice": I18nString(
        en="⏰ This fix will be auto-closed after {hours} hours if no response",
        zh="⏰ 如果 {hours} 小时内无响应，此修复将自动关闭"
    ),
    "confirmed_message": I18nString(
        en="✅ Fix confirmed! Creating formal PR...",
        zh="✅ 修复已确认！正在创建正式 PR..."
    ),
    "rejected_message": I18nString(
        en="❌ Fix rejected. Closing preview PR...",
        zh="❌ 修复已拒绝。正在关闭预览 PR..."
    ),
    "auto_applied_message": I18nString(
        en="🤖 Fix auto-applied (confirm_mode=auto). PR created: #{pr_number}",
        zh="🤖 修复已自动应用 (confirm_mode=auto)。PR 已创建: #{pr_number}"
    ),
    
    # 处理状态消息
    "processing_started": I18nString(
        en="🔍 Analyzing issue...",
        zh="🔍 正在分析问题..."
    ),
    "analyzing_code": I18nString(
        en="🔍 Analyzing code context...",
        zh="🔍 正在分析代码上下文..."
    ),
    "generating_fix": I18nString(
        en="🔧 Generating fix...",
        zh="🔧 正在生成修复方案..."
    ),
    "applying_fix": I18nString(
        en="📝 Applying fix...",
        zh="📝 正在应用修复..."
    ),
    "completed": I18nString(
        en="✅ Completed",
        zh="✅ 已完成"
    ),
    "failed": I18nString(
        en="❌ Failed: {reason}",
        zh="❌ 失败: {reason}"
    ),
    
    # 错误消息
    "error_no_fix_needed": I18nString(
        en="This issue doesn't require code changes",
        zh="此问题不需要代码修改"
    ),
    "error_cannot_locate": I18nString(
        en="Cannot locate relevant code files",
        zh="无法定位相关代码文件"
    ),
    "error_apply_failed": I18nString(
        en="Failed to apply fix: {error}",
        zh="应用修复失败: {error}"
    ),
    
    # 文件操作消息
    "files_modified": I18nString(
        en="Modified files:",
        zh="修改的文件:"
    ),
    "file_added": I18nString(
        en="Added: {path}",
        zh="新增: {path}"
    ),
    "file_modified": I18nString(
        en="Modified: {path}",
        zh="修改: {path}"
    ),
    "file_deleted": I18nString(
        en="Deleted: {path}",
        zh="删除: {path}"
    ),
}


class I18n:
    """
    国际化管理器
    
    功能：
    - 自动检测文本语言
    - 获取对应语言的消息
    - 支持变量替换
    """
    
    def __init__(self, default_language: str = "auto"):
        self.default_language = default_language
    
    def detect_language(self, text: str) -> str:
        """
        检测文本语言
        
        简单启发式：
        - 包含中文字符 -> zh
        - 否则 -> en
        """
        if not text:
            return "en"
        
        # 统计中文字符数量
        chinese_chars = len(re.findall(r'[\u4e00-\u9fff]', text))
        total_chars = len(re.sub(r'\s', '', text))
        
        if total_chars == 0:
            return "en"
        
        # 如果中文字符占比超过 10%，认为是中文
        if chinese_chars / total_chars > 0.1:
            return "zh"
        
        return "en"
    
    def get(self, key: str, lang: str = "auto", **kwargs) -> str:
        """
        获取国际化消息
        
        Args:
            key: 消息键
            lang: 语言代码 (auto/en/zh)
            **kwargs: 变量替换
        
        Returns:
            本地化后的字符串
        """
        # 确定语言
        if lang == "auto":
            lang = self.default_language
        if lang == "auto":
            lang = "en"  # 默认英文
        
        # 获取消息模板
        i18n_str = MESSAGES.get(key)
        if not i18n_str:
            logger.warning("i18n.key_not_found", key=key)
            return key
        
        # 获取对应语言
        message = i18n_str.get(lang)
        
        # 变量替换
        try:
            message = message.format(**kwargs)
        except KeyError as e:
            logger.warning("i18n.format_error", key=key, error=str(e))
        
        return message
    
    def get_with_detect(self, key: str, text_sample: str, **kwargs) -> str:
        """
        基于样本文本自动检测语言并获取消息
        """
        lang = self.detect_language(text_sample)
        return self.get(key, lang, **kwargs)


# 全局单例
_i18n: Optional[I18n] = None


def get_i18n() -> I18n:
    """获取 I18n 单例"""
    global _i18n
    if _i18n is None:
        # 从配置读取默认语言
        try:
            from core.config import get_config
            config = get_config()
            default_lang = getattr(config, 'i18n', {}).get('default_language', 'auto')
        except Exception:
            default_lang = 'auto'
        
        _i18n = I18n(default_lang)
    return _i18n


def t(key: str, lang: str = "auto", **kwargs) -> str:
    """
    快捷翻译函数
    
    示例:
        t("fix_generated", lang="zh", file_count=3)
        # -> "已为 3 个文件生成修复方案"
    """
    return get_i18n().get(key, lang, **kwargs)


def t_detect(key: str, text_sample: str, **kwargs) -> str:
    """
    自动检测语言的快捷翻译
    
    示例:
        t_detect("fix_generated", issue_body, file_count=3)
    """
    return get_i18n().get_with_detect(key, text_sample, **kwargs)