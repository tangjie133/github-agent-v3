"""
LLM Manager 测试

包含：
- 单元测试（mock）
- 契约测试（可选，需要真实服务）
"""

import sys
import os

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
from unittest.mock import Mock, AsyncMock, patch
import asyncio

from core.llm.manager import LLMManager, LLMProvider, LLMResponse
from core.llm.ollama_client import OllamaClient
from core.llm.openclaw_client import OpenClawClient
from core.llm.template_generator import TemplateGenerator


class TestLLMManager:
    """LLM Manager 单元测试"""
    
    @pytest.fixture
    def mock_config(self):
        """模拟配置"""
        config = Mock()
        config.llm.primary_provider = 'ollama'
        config.llm.fallback_provider = 'openclaw'
        config.llm.ollama_host = 'http://localhost:11434'
        config.llm.ollama_model_code = 'qwen3-coder:30b'
        config.llm.ollama_model_intent = 'qwen3:8b'
        config.llm.ollama_model_answer = 'qwen3-coder:14b'
        config.llm.ollama_timeout = 300
        config.llm.openclaw_enabled = True
        config.llm.openclaw_url = 'http://localhost:3000'
        config.llm.openclaw_timeout = 60
        return config
    
    def test_init(self, mock_config):
        """测试初始化"""
        with patch('core.llm.manager.get_config', return_value=mock_config):
            manager = LLMManager()
            assert manager.primary_provider == LLMProvider.OLLAMA
            assert manager.fallback_provider == LLMProvider.OPENCLAW
    
    @pytest.mark.asyncio
    async def test_generate_with_retry_success(self, mock_config):
        """测试生成成功"""
        mock_response = LLMResponse(
            text="test response",
            provider=LLMProvider.OLLAMA,
            model="test-model",
            latency_ms=100
        )
        
        with patch('core.llm.manager.get_config', return_value=mock_config):
            manager = LLMManager()
            with patch.object(manager, '_try_generate', 
                             return_value=mock_response) as mock_try:
                response = await manager.generate(
                    prompt="test",
                    task_type="code",
                    max_retries=2
                )
        
        assert response.text == "test response"
        assert response.provider == LLMProvider.OLLAMA
    
    @pytest.mark.asyncio
    async def test_generate_fallback(self, mock_config):
        """测试 fallback 机制"""
        mock_response = LLMResponse(
            text="fallback response",
            provider=LLMProvider.OPENCLAW,
            model="test-model",
            latency_ms=100
        )
        
        with patch('core.llm.manager.get_config', return_value=mock_config):
            manager = LLMManager()
            # 主提供商失败
            with patch.object(manager, '_try_generate', 
                             side_effect=[Exception("primary failed"), 
                                         mock_response]) as mock_try:
                response = await manager.generate(
                    prompt="test",
                    task_type="code"
                )
        
        assert response.text == "fallback response"
        assert response.provider == LLMProvider.OPENCLAW
    
    @pytest.mark.asyncio
    async def test_generate_all_fail(self, mock_config):
        """测试全部失败时使用模板"""
        with patch('core.llm.manager.get_config', return_value=mock_config):
            manager = LLMManager()
            with patch.object(manager, '_try_generate', 
                             side_effect=Exception("all failed")) as mock_try:
                response = await manager.generate(
                    prompt="test",
                    task_type="code",
                    max_retries=1
                )
        
        # 应该返回模板响应
        assert "模板生成" in response.text or "fallback" in response.text.lower()
        assert response.provider == LLMProvider.TEMPLATE


class TestOllamaClient:
    """Ollama 客户端测试"""
    
    @pytest.mark.asyncio
    async def test_health_check_success(self):
        """测试健康检查成功"""
        client = OllamaClient()
        
        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session
            
            mock_response = AsyncMock()
            mock_response.status = 200
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)
            
            mock_session.get = Mock(return_value=mock_response)
            
            result = await client.health_check()
            assert result is True
    
    @pytest.mark.asyncio
    async def test_health_check_failure(self):
        """测试健康检查失败"""
        client = OllamaClient()
        
        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session
            
            mock_response = AsyncMock()
            mock_response.status = 500
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)
            
            mock_session.get = Mock(return_value=mock_response)
            
            result = await client.health_check()
            assert result is False


class TestOpenClawClient:
    """OpenClaw 客户端测试"""
    
    @pytest.mark.asyncio
    async def test_chat_completion_mock(self):
        """使用 mock 测试对话"""
        client = OpenClawClient(api_key="test-key")
        
        mock_response_data = {
            "choices": [{
                "message": {"content": "AI response"}
            }]
        }
        
        with patch('aiohttp.ClientSession') as MockSession:
            mock_session = Mock()
            MockSession.return_value = mock_session
            
            mock_response = AsyncMock()
            mock_response.json = AsyncMock(return_value=mock_response_data)
            mock_response.raise_for_status = Mock()
            mock_response.__aenter__ = AsyncMock(return_value=mock_response)
            mock_response.__aexit__ = AsyncMock(return_value=False)
            
            mock_session.post = Mock(return_value=mock_response)
            
            result = await client.chat_completion([
                {"role": "user", "content": "test"}
            ])
            assert result == "AI response"


class TestTemplateGenerator:
    """模板生成器测试"""
    
    @pytest.mark.asyncio
    async def test_generate_fix(self):
        """测试生成修复建议"""
        generator = TemplateGenerator()
        
        result = await generator.generate_fix(
            issue_title="IndexError in process_data",
            issue_body="处理数据时出现 IndexError",
            error_logs="IndexError: list index out of range",
            file_context=[{"path": "src/data.py", "content": "def process()..."}]
        )
        
        assert "模板生成" in result
        assert "IndexError" in result
        assert "超出范围" in result
    
    @pytest.mark.asyncio
    async def test_generate_response(self):
        """测试通用响应"""
        generator = TemplateGenerator()
        
        result = await generator.generate_response("Help me fix this bug")
        
        assert "自动响应" in result
        assert "AI 服务暂时不可用" in result
    
    @pytest.mark.asyncio
    async def test_health_check_always_true(self):
        """测试模板生成器总是可用"""
        generator = TemplateGenerator()
        result = await generator.health_check()
        assert result is True


@pytest.mark.skip(reason="需要真实 Ollama 服务")
class TestOllamaContract:
    """Ollama 契约测试（需要真实服务）"""
    
    @pytest.fixture
    async def client(self):
        """创建真实客户端"""
        client = OllamaClient()
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_health_check_real(self, client):
        """真实健康检查"""
        result = await client.health_check()
        assert isinstance(result, bool)
    
    @pytest.mark.asyncio
    async def test_list_models(self, client):
        """列出模型"""
        models = await client.list_models()
        assert isinstance(models, list)
    
    @pytest.mark.asyncio
    async def test_generate_simple(self, client):
        """简单生成测试"""
        # 跳过如果模型不可用
        models = await client.list_models()
        if not models:
            pytest.skip("No models available")
        
        result = await client.generate(
            model=models[0],
            prompt="Say 'hello' in one word",
            timeout=30
        )
        
        assert "response" in result
        assert isinstance(result["response"], str)


@pytest.mark.skip(reason="需要真实 OpenClaw 服务")
class TestOpenClawContract:
    """OpenClaw 契约测试（需要真实服务）"""
    
    @pytest.fixture
    async def client(self):
        """创建真实客户端 - 需要设置 OPENCLAW_API_KEY"""
        import os
        api_key = os.getenv("OPENCLAW_API_KEY")
        if not api_key:
            pytest.skip("OPENCLAW_API_KEY not set")
        
        client = OpenClawClient(api_key=api_key)
        yield client
        await client.close()
    
    @pytest.mark.asyncio
    async def test_chat_completion_real(self, client):
        """真实对话测试"""
        result = await client.chat_completion([
            {"role": "user", "content": "Say hello in Chinese"}
        ])
        
        assert isinstance(result, str)
        assert len(result) > 0
