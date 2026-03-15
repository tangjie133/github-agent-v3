"""
i18n 模块测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from core.i18n import I18n, get_i18n, t, t_detect, Language


class TestI18n:
    """国际化模块测试"""
    
    def test_detect_language_english(self):
        """测试英文检测"""
        i18n = I18n()
        assert i18n.detect_language("This is an English text") == "en"
        assert i18n.detect_language("Hello World") == "en"
    
    def test_detect_language_chinese(self):
        """测试中文检测"""
        i18n = I18n()
        assert i18n.detect_language("这是一个中文文本") == "zh"
        assert i18n.detect_language("你好世界") == "zh"
    
    def test_detect_language_mixed(self):
        """测试混合文本检测"""
        i18n = I18n()
        # 中文字符超过 10% 应识别为中文
        assert i18n.detect_language("This has some 中文 mixed") == "zh"
        # 少量中文应识别为英文
        assert i18n.detect_language("This has 一 Chinese character") == "en"
    
    def test_detect_language_empty(self):
        """测试空文本"""
        i18n = I18n()
        assert i18n.detect_language("") == "en"
        assert i18n.detect_language(None) == "en"
    
    def test_get_message_english(self):
        """测试获取英文消息"""
        i18n = I18n()
        msg = i18n.get("fix_generated", "en", file_count=3)
        assert "3" in msg
        assert "file" in msg.lower()
    
    def test_get_message_chinese(self):
        """测试获取中文消息"""
        i18n = I18n()
        msg = i18n.get("fix_generated", "zh", file_count=3)
        assert "3" in msg
        assert "文件" in msg
    
    def test_get_message_auto(self):
        """测试自动语言检测获取消息"""
        i18n = I18n()
        
        # 通过中文样本文本
        msg = i18n.get_with_detect("fix_generated", "这是一个中文问题", file_count=3)
        assert "文件" in msg
        
        # 通过英文样本文本
        msg = i18n.get_with_detect("fix_generated", "This is an English issue", file_count=3)
        assert "file" in msg.lower()
    
    def test_get_unknown_key(self):
        """测试未知键返回键名"""
        i18n = I18n()
        msg = i18n.get("unknown_key_12345", "en")
        assert msg == "unknown_key_12345"


class TestTFunctions:
    """快捷翻译函数测试"""
    
    def test_t_function(self):
        """测试 t() 函数"""
        msg = t("completed", "en")
        assert "Completed" in msg or "completed" in msg.lower()
        
        msg = t("completed", "zh")
        assert "完成" in msg
    
    def test_t_detect_function(self):
        """测试 t_detect() 函数"""
        msg = t_detect("completed", "中文文本")
        assert "完成" in msg
        
        msg = t_detect("completed", "English text")
        assert "Completed" in msg or "completed" in msg.lower()
    
    def test_t_with_variables(self):
        """测试带变量的翻译"""
        msg = t("fix_generated", "en", file_count=5)
        assert "5" in msg


class TestI18nSingleton:
    """i18n 单例测试"""
    
    def test_singleton(self):
        """测试单例模式"""
        i18n1 = get_i18n()
        i18n2 = get_i18n()
        assert i18n1 is i18n2