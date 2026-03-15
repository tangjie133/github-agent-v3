"""
人工确认机制测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import Mock, patch
from datetime import datetime, timedelta, timezone

from core.confirmation import (
    ConfirmationManager,
    ConfirmationRecord,
    ConfirmMode,
    ConfirmStatus,
    get_confirmation_manager
)


class TestConfirmationRecord:
    """确认记录测试"""
    
    def test_is_expired_pending(self):
        """测试待确认状态超时检测"""
        record = ConfirmationRecord(
            issue_number=1,
            repo="owner/repo",
            status=ConfirmStatus.PENDING,
            created_at=datetime.now(timezone.utc) - timedelta(hours=200)
        )
        assert record.is_expired(168) is True
    
    def test_is_expired_not_pending(self):
        """测试已解决状态不超时"""
        record = ConfirmationRecord(
            issue_number=1,
            repo="owner/repo",
            status=ConfirmStatus.CONFIRMED,
            created_at=datetime.now(timezone.utc) - timedelta(hours=200)
        )
        assert record.is_expired(168) is False
    
    def test_is_expired_not_yet(self):
        """测试未超时"""
        record = ConfirmationRecord(
            issue_number=1,
            repo="owner/repo",
            status=ConfirmStatus.PENDING,
            created_at=datetime.now(timezone.utc) - timedelta(hours=10)
        )
        assert record.is_expired(168) is False
    
    def test_to_dict(self):
        """测试转换为字典"""
        record = ConfirmationRecord(
            issue_number=1,
            repo="owner/repo",
            preview_pr_number=42,
            status=ConfirmStatus.PENDING,
            files_changed=["a.py", "b.py"]
        )
        
        d = record.to_dict()
        assert d["issue_number"] == 1
        assert d["preview_pr_number"] == 42
        assert d["status"] == "pending"
        assert len(d["files_changed"]) == 2


class TestConfirmationManager:
    """确认管理器测试"""
    
    @pytest.fixture
    def mock_config_manual(self):
        """手动模式配置"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        return config
    
    @pytest.fixture
    def mock_config_auto(self):
        """自动模式配置"""
        config = Mock()
        config.processing.confirm_mode = 'auto'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        return config
    
    @pytest.mark.asyncio
    async def test_create_confirmation_manual(self, mock_config_manual):
        """测试手动模式创建确认"""
        with patch('core.confirmation.get_config', return_value=mock_config_manual):
            mgr = ConfirmationManager()
            
            record = await mgr.create_confirmation(
                repo="owner/repo",
                issue_number=1,
                preview_pr_number=42,
                files_changed=["a.py"],
                confidence=0.95
            )
            
            assert record.status == ConfirmStatus.PENDING
            assert record.preview_pr_number == 42
    
    @pytest.mark.asyncio
    async def test_create_confirmation_auto_high_confidence(self, mock_config_auto):
        """测试自动模式高置信度自动通过"""
        with patch('core.confirmation.get_config', return_value=mock_config_auto):
            mgr = ConfirmationManager()
            
            record = await mgr.create_confirmation(
                repo="owner/repo",
                issue_number=1,
                preview_pr_number=42,
                files_changed=["a.py"],
                confidence=0.95  # > 0.9 threshold
            )
            
            assert record.status == ConfirmStatus.AUTO
            assert record.resolved_by == "system(auto)"
    
    @pytest.mark.asyncio
    async def test_create_confirmation_auto_low_confidence(self, mock_config_auto):
        """测试自动模式低置信度仍需确认"""
        with patch('core.confirmation.get_config', return_value=mock_config_auto):
            mgr = ConfirmationManager()
            
            record = await mgr.create_confirmation(
                repo="owner/repo",
                issue_number=1,
                preview_pr_number=42,
                files_changed=["a.py"],
                confidence=0.5  # < 0.9 threshold
            )
            
            assert record.status == ConfirmStatus.PENDING
    
    @pytest.mark.asyncio
    async def test_parse_user_response_confirm(self):
        """测试解析确认响应"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            
            # 中文确认
            result = await mgr.parse_user_response("确认应用这个修复")
            assert result == ConfirmStatus.CONFIRMED
            
            # 英文确认
            result = await mgr.parse_user_response("LGTM, please confirm")
            assert result == ConfirmStatus.CONFIRMED
            
            result = await mgr.parse_user_response("approve this fix")
            assert result == ConfirmStatus.CONFIRMED
    
    @pytest.mark.asyncio
    async def test_parse_user_response_reject(self):
        """测试解析拒绝响应"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            
            # 中文拒绝
            result = await mgr.parse_user_response("拒绝这个修复")
            assert result == ConfirmStatus.REJECTED
            
            # 英文拒绝
            result = await mgr.parse_user_response("reject this change")
            assert result == ConfirmStatus.REJECTED
            
            result = await mgr.parse_user_response("please cancel")
            assert result == ConfirmStatus.REJECTED
    
    @pytest.mark.asyncio
    async def test_parse_user_response_none(self):
        """测试解析非确认响应"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            
            result = await mgr.parse_user_response("Thanks for the fix")
            assert result is None
            
            result = await mgr.parse_user_response("Let me check")
            assert result is None
    
    @pytest.mark.asyncio
    async def test_handle_user_response_confirm(self):
        """测试处理用户确认响应"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            
            # 先创建记录
            await mgr.create_confirmation(
                repo="owner/repo",
                issue_number=1,
                preview_pr_number=42,
                files_changed=["a.py"]
            )
            
            # 处理确认响应
            result = await mgr.handle_user_response(
                "owner/repo", 1, "确认", "user123"
            )
            
            assert result == ConfirmStatus.CONFIRMED
            
            # 验证记录已更新
            record = mgr.get_record("owner/repo", 1)
            assert record.status == ConfirmStatus.CONFIRMED
            assert record.resolved_by == "user123"
    
    @pytest.mark.asyncio
    async def test_check_timeouts(self):
        """测试超时检查"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 1  # 1小时超时
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            
            # 创建超时记录
            await mgr.create_confirmation(
                repo="owner/repo",
                issue_number=1,
                preview_pr_number=42,
                files_changed=["a.py"]
            )
            
            # 修改创建时间为2小时前
            key = mgr._make_key("owner/repo", 1)
            mgr._records[key].created_at = datetime.now(timezone.utc) - timedelta(hours=2)
            
            # 检查超时
            expired = await mgr.check_timeouts()
            
            assert len(expired) == 1
            assert expired[0].status == ConfirmStatus.TIMEOUT
    
    def test_is_auto_mode(self):
        """测试自动模式检测"""
        config = Mock()
        config.processing.confirm_mode = 'auto'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            assert mgr.is_auto_mode() is True
    
    def test_get_confirmation_message(self):
        """测试生成确认消息"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr = ConfirmationManager()
            
            record = ConfirmationRecord(
                issue_number=1,
                repo="owner/repo",
                preview_pr_number=42,
                files_changed=["a.py", "b.py"]
            )
            
            # 中文消息
            msg = mgr.get_confirmation_message(record, "中文 Issue")
            assert "修复方案预览" in msg
            assert "42" in msg
            assert "a.py" in msg
            assert "确认应用" in msg
            
            # 英文消息
            msg = mgr.get_confirmation_message(record, "English Issue")
            assert "Fix Preview" in msg
            assert "Confirm Apply" in msg


class TestConfirmationSingleton:
    """确认管理器单例测试"""
    
    def test_singleton(self):
        """测试单例模式"""
        config = Mock()
        config.processing.confirm_mode = 'manual'
        config.processing.confirm_timeout_hours = 168
        config.processing.auto_confirm_threshold = 0.9
        
        with patch('core.confirmation.get_config', return_value=config):
            mgr1 = get_confirmation_manager()
            mgr2 = get_confirmation_manager()
            assert mgr1 is mgr2