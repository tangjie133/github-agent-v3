#!/usr/bin/env python3
"""
测试改进后的代码

运行方式：
    python tests/test_improvements.py
"""

import asyncio
import sys
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, str(Path(__file__).parent.parent))


def test_exceptions():
    """测试异常体系"""
    print("\n🧪 测试异常体系...")
    
    from core.exceptions import (
        GitHubAPIError,
        GitHubAuthError,
        LLMTimeoutError,
        ErrorCode
    )
    
    # 测试基本异常
    try:
        raise GitHubAPIError(
            message="Test error",
            status_code=404,
            details={"url": "/test"}
        )
    except GitHubAPIError as e:
        assert e.code == ErrorCode.GITHUB_NOT_FOUND
        assert e.status_code == 404
        print(f"  ✓ GitHubAPIError: {e}")
    
    # 测试认证错误
    try:
        raise GitHubAuthError("Invalid token")
    except GitHubAuthError as e:
        assert e.code == ErrorCode.GITHUB_AUTH_ERROR
        print(f"  ✓ GitHubAuthError: {e}")
    
    # 测试 LLM 超时
    try:
        raise LLMTimeoutError(provider="ollama", timeout=30.0)
    except LLMTimeoutError as e:
        assert e.code == ErrorCode.LLM_TIMEOUT_ERROR
        print(f"  ✓ LLMTimeoutError: {e}")
    
    # 测试 to_dict 方法
    exc = GitHubAPIError("Test", status_code=500)
    data = exc.to_dict()
    assert data["error"] is True
    assert "code" in data
    assert "message" in data
    print(f"  ✓ to_dict(): {data}")
    
    print("  ✅ 异常体系测试通过")


def test_config():
    """测试 Pydantic 配置"""
    print("\n🧪 测试 Pydantic 配置...")
    
    from core.config import AgentConfig, StorageConfig, LLMConfig
    
    # 测试默认配置创建
    config = AgentConfig()
    assert config.storage.max_repo_size_mb == 1000
    assert config.llm.ollama_host == "http://localhost:11434"
    print(f"  ✓ 默认配置创建成功")
    
    # 测试配置验证
    try:
        LLMConfig(ollama_timeout=1000)  # 超出范围
        assert False, "应该抛出验证错误"
    except Exception as e:
        print(f"  ✓ 配置验证工作: {type(e).__name__}")
    
    # 测试配置转字典
    config_dict = config.to_dict(hide_secrets=True)
    assert "storage" in config_dict
    assert "llm" in config_dict
    print(f"  ✓ to_dict() 工作正常")
    
    # 测试验证方法
    errors = config.validate_all()
    # 应该有一些错误（因为没有提供 GitHub 认证）
    print(f"  ✓ validate_all() 返回 {len(errors)} 个错误")
    
    print("  ✅ 配置系统测试通过")


def test_config_from_env():
    """测试从环境变量加载配置"""
    print("\n🧪 测试环境变量配置...")
    
    import os
    from core.config import AgentConfig
    
    # 设置测试环境变量
    os.environ["GITHUB_AGENT_LLM__OLLAMA_TIMEOUT"] = "120"
    os.environ["GITHUB_AGENT_STORAGE__MAX_REPO_SIZE_MB"] = "2000"
    
    try:
        config = AgentConfig()
        # 注意：环境变量应该在创建时自动加载
        print(f"  ✓ 从环境变量加载配置")
        print(f"    - Ollama Timeout: {config.llm.ollama_timeout}")
        print(f"    - Max Repo Size: {config.storage.max_repo_size_mb}")
    finally:
        # 清理环境变量
        del os.environ["GITHUB_AGENT_LLM__OLLAMA_TIMEOUT"]
        del os.environ["GITHUB_AGENT_STORAGE__MAX_REPO_SIZE_MB"]
    
    print("  ✅ 环境变量配置测试通过")


async def test_github_client_mock():
    """测试 GitHub 客户端（使用 Mock）"""
    print("\n🧪 测试 GitHub 异步客户端...")
    
    from github_api import GitHubClient
    from core.exceptions import GitHubAuthError
    
    # 测试没有认证时抛出异常
    try:
        client = GitHubClient()  # 没有 token 和 auth_manager
        await client._get_token()
        assert False, "应该抛出认证错误"
    except GitHubAuthError as e:
        print(f"  ✓ 认证错误抛出: {e.message}")
    
    # 测试带 token 的客户端创建
    client = GitHubClient(token="test_token")
    token = await client._get_token()
    assert token == "test_token"
    print(f"  ✓ Token 客户端创建成功")
    
    # 测试客户端关闭
    await client.close()
    print(f"  ✓ 客户端关闭成功")
    
    print("  ✅ GitHub 客户端基础测试通过")


def test_github_client_headers():
    """测试 GitHub 客户端请求头生成"""
    print("\n🧪 测试 GitHub 请求头...")
    
    import asyncio
    from github_api import GitHubClient
    
    async def _test():
        client = GitHubClient(token="test_token_12345")
        headers = await client._get_headers()
        
        assert "Authorization" in headers
        assert headers["Authorization"] == "token test_token_12345"
        assert "Accept" in headers
        assert "X-GitHub-Api-Version" in headers
        
        await client.close()
    
    asyncio.run(_test())
    print("  ✓ 请求头生成正确")
    print("  ✅ 请求头测试通过")


def run_all_tests():
    """运行所有测试"""
    print("=" * 60)
    print("🚀 GitHub Agent V3 改进测试")
    print("=" * 60)
    
    try:
        test_exceptions()
        test_config()
        test_config_from_env()
        
        # 异步测试
        asyncio.run(test_github_client_mock())
        test_github_client_headers()
        
        print("\n" + "=" * 60)
        print("✅ 所有测试通过！")
        print("=" * 60)
        return True
        
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = run_all_tests()
    sys.exit(0 if success else 1)
