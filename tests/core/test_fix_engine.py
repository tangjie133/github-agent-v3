"""
修复引擎测试
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import Mock, AsyncMock, patch

from core.fix.engine import MultiFileFixEngine
from core.fix.models import (
    FixPlan, FixStatus, FilePatch, FileLocation,
    ChangeType, ValidationResult
)


class TestMultiFileFixEngine:
    """多文件修复引擎测试"""
    
    @pytest.fixture
    def mock_config(self):
        """模拟配置"""
        config = Mock()
        config.llm.primary_provider = 'ollama'
        return config
    
    @pytest.fixture
    def mock_llm_response(self):
        """模拟 LLM 响应"""
        return Mock(
            text='''{
                "error_analysis": "Index out of range error",
                "fix_strategy": "Add bounds checking",
                "affected_files": ["src/data.py"],
                "dependencies": [],
                "effort": "small",
                "confidence": 0.9
            }''',
            provider=Mock(value='ollama'),
            model='test-model',
            latency_ms=100
        )
    
    @pytest.mark.asyncio
    async def test_analyze_issue(self, mock_config, mock_llm_response):
        """测试 Issue 分析"""
        with patch('core.fix.engine.get_config', return_value=mock_config):
            engine = MultiFileFixEngine()
            
            # 模拟 LLM
            mock_llm = Mock()
            mock_llm.generate = AsyncMock(return_value=mock_llm_response)
            engine.llm = mock_llm
            
            plan = await engine.analyze_issue(
                issue_number=1,
                repo="owner/repo",
                issue_title="IndexError in data processing",
                issue_body="Getting index out of range",
                error_logs="IndexError: list index out of range"
            )
            
            assert plan.issue_number == 1
            assert plan.repo == "owner/repo"
            assert plan.status == FixStatus.ANALYZING
            assert len(plan.affected_files) == 1
            assert plan.affected_files[0].path == "src/data.py"
            assert plan.confidence == 0.9
    
    @pytest.mark.asyncio
    async def test_generate_patches(self, mock_config):
        """测试补丁生成"""
        with patch('core.fix.engine.get_config', return_value=mock_config):
            engine = MultiFileFixEngine()
            
            # 模拟 LLM 响应
            mock_response = Mock(
                text='''def process_data(data):
    if not data:
        return []
    return [x * 2 for x in data]''',
                provider=Mock(value='ollama'),
                model='test-model',
                latency_ms=100
            )
            
            mock_llm = Mock()
            mock_llm.generate = AsyncMock(return_value=mock_response)
            engine.llm = mock_llm
            
            plan = FixPlan(
                issue_number=1,
                repo="owner/repo",
                title="Fix bug",
                affected_files=[FileLocation(path="src/data.py")]
            )
            
            file_contents = {
                "src/data.py": "def process_data(data):\n    return [x * 2 for x in data]"
            }
            
            plan = await engine.generate_patches(plan, file_contents)
            
            assert plan.status == FixStatus.VALIDATING
            assert len(plan.patches) == 1
            assert plan.patches[0].path == "src/data.py"
            assert plan.patches[0].change_type == ChangeType.MODIFY
    
    @pytest.mark.asyncio
    async def test_validate_patches_valid(self):
        """测试有效补丁验证"""
        engine = MultiFileFixEngine()
        
        plan = FixPlan(
            issue_number=1,
            repo="owner/repo"
        )
        
        # 有效补丁
        plan.patches = [
            FilePatch(
                path="src/data.py",
                change_type=ChangeType.MODIFY,
                old_content="old",
                new_content="new"
            )
        ]
        
        result = await engine.validate_patches(plan)
        
        assert result.is_valid is True
        assert len(result.errors) == 0
    
    @pytest.mark.asyncio
    async def test_validate_patches_invalid_modify(self):
        """测试无效修改补丁验证"""
        engine = MultiFileFixEngine()
        
        plan = FixPlan(
            issue_number=1,
            repo="owner/repo"
        )
        
        # 无效的修改补丁（缺少 old_content）
        plan.patches = [
            FilePatch(
                path="src/data.py",
                change_type=ChangeType.MODIFY,
                old_content=None,
                new_content="new"
            )
        ]
        
        result = await engine.validate_patches(plan)
        
        assert result.is_valid is False
        assert len(result.errors) > 0
    
    @pytest.mark.asyncio
    async def test_validate_patches_invalid_add(self):
        """测试无效新增补丁验证"""
        engine = MultiFileFixEngine()
        
        plan = FixPlan(
            issue_number=1,
            repo="owner/repo"
        )
        
        # 无效的新增补丁（缺少 new_content）
        plan.patches = [
            FilePatch(
                path="src/new.py",
                change_type=ChangeType.ADD,
                new_content=None
            )
        ]
        
        result = await engine.validate_patches(plan)
        
        assert result.is_valid is False
        assert len(result.errors) > 0
    
    def test_parse_analysis_response_valid(self):
        """测试解析有效的分析响应"""
        engine = MultiFileFixEngine()
        
        response = '''{
            "error_analysis": "Test error",
            "fix_strategy": "Fix it",
            "affected_files": ["a.py", "b.py"],
            "dependencies": ["a.py depends on b.py"],
            "effort": "medium",
            "confidence": 0.85
        }'''
        
        result = engine._parse_analysis_response(response)
        
        assert result["error_analysis"] == "Test error"
        assert len(result["affected_files"]) == 2
        assert result["effort"] == "medium"
        assert result["confidence"] == 0.85
    
    def test_parse_analysis_response_invalid(self):
        """测试解析无效的分析响应"""
        engine = MultiFileFixEngine()
        
        response = "Not valid JSON"
        
        result = engine._parse_analysis_response(response)
        
        assert result["error_analysis"] == "Failed to parse LLM response"
        assert result["confidence"] == 0.0
        assert len(result["affected_files"]) == 0


class TestFilePatch:
    """文件补丁测试"""
    
    def test_to_diff_add(self):
        """测试新增文件的 diff 生成"""
        patch = FilePatch(
            path="src/new.py",
            change_type=ChangeType.ADD,
            new_content="def hello():\n    pass"
        )
        
        diff = patch.to_diff()
        
        assert "--- /dev/null" in diff
        assert "+++ b/src/new.py" in diff
        assert "+def hello():" in diff
    
    def test_to_diff_delete(self):
        """测试删除文件的 diff 生成"""
        patch = FilePatch(
            path="src/old.py",
            change_type=ChangeType.DELETE,
            old_content="def old():\n    pass"
        )
        
        diff = patch.to_diff()
        
        assert "--- a/src/old.py" in diff
        assert "+++ /dev/null" in diff
        assert "-def old():" in diff
    
    def test_to_diff_modify(self):
        """测试修改文件的 diff 生成"""
        patch = FilePatch(
            path="src/modify.py",
            change_type=ChangeType.MODIFY,
            old_content="old line",
            new_content="new line"
        )
        
        diff = patch.to_diff()
        
        assert "--- a/src/modify.py" in diff
        assert "+++ b/src/modify.py" in diff


class TestFixPlan:
    """修复计划测试"""
    
    def test_to_dict(self):
        """测试转换为字典"""
        plan = FixPlan(
            issue_number=42,
            repo="owner/repo",
            title="Fix bug",
            affected_files=[FileLocation(path="a.py")],
            confidence=0.9,
            status=FixStatus.READY
        )
        
        d = plan.to_dict()
        
        assert d["issue_number"] == 42
        assert d["repo"] == "owner/repo"
        assert d["confidence"] == 0.9
        assert d["status"] == "ready"
        assert len(d["affected_files"]) == 1