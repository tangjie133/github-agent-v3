#!/usr/bin/env python3
"""
GitHub Agent V3 诊断脚本

检查：
1. Python 版本
2. 依赖安装
3. 配置有效性
4. 关键服务连接（Redis, Ollama）
5. GitHub API 认证
"""

import sys
import os

# 添加项目路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def check_python_version():
    """检查 Python 版本"""
    print("=" * 60)
    print("1. Python 版本检查")
    print("=" * 60)
    
    version = sys.version_info
    print(f"Python: {sys.version}")
    
    if version >= (3, 12):
        print("✅ Python 3.12+ 支持")
    elif version >= (3, 10):
        print("⚠️  Python 3.10-3.11 可用，但建议使用 3.12+")
    else:
        print("❌ Python 3.10+  required")
        return False
    
    return True

def check_dependencies():
    """检查依赖"""
    print("\n" + "=" * 60)
    print("2. 依赖检查")
    print("=" * 60)
    
    required = {
        "fastapi": "FastAPI",
        "uvicorn": "Uvicorn",
        "aiohttp": "aiohttp",
        "redis": "Redis",
        "yaml": "PyYAML",
        "jwt": "PyJWT",
    }
    
    optional = {
        "github": "PyGithub",
    }
    
    all_ok = True
    
    for module, name in required.items():
        try:
            __import__(module)
            print(f"✅ {name}")
        except ImportError:
            print(f"❌ {name} - 请运行: pip install -r requirements.txt")
            all_ok = False
    
    print("\n可选依赖:")
    for module, name in optional.items():
        try:
            __import__(module)
            print(f"✅ {name}")
        except ImportError:
            print(f"⚠️  {name} - 未安装（可选）")
    
    return all_ok

def check_config():
    """检查配置"""
    print("\n" + "=" * 60)
    print("3. 配置检查")
    print("=" * 60)
    
    try:
        from core.config import get_config
        config = get_config()
        
        # 检查 GitHub 认证
        github_token = os.getenv("GITHUB_TOKEN")
        github_app_id = os.getenv("GITHUB_APP_ID")
        
        if github_token:
            print(f"✅ GITHUB_TOKEN: {'*' * 10}{github_token[-4:]}")
        elif github_app_id:
            print(f"✅ GITHUB_APP_ID: {github_app_id}")
            private_key = os.getenv("GITHUB_APP_PRIVATE_KEY")
            if private_key:
                print("✅ GITHUB_APP_PRIVATE_KEY: 已设置")
            else:
                print("❌ GITHUB_APP_PRIVATE_KEY: 未设置")
        else:
            print("⚠️  GitHub 认证: 未配置 (GITHUB_TOKEN 或 GITHUB_APP_ID)")
        
        # 检查 Webhook Secret
        webhook_secret = config.github.webhook_secret or os.getenv("GITHUB_WEBHOOK_SECRET")
        if webhook_secret:
            print("✅ Webhook Secret: 已设置")
        else:
            print("⚠️  Webhook Secret: 未设置（生产环境必需）")
        
        # 检查 Redis
        redis_url = config.queue.redis_url
        print(f"ℹ️  Redis URL: {redis_url}")
        
        # 检查 LLM 配置
        print(f"ℹ️  Primary LLM: {config.llm.primary_provider}")
        print(f"ℹ️  Ollama Host: {config.llm.ollama_host}")
        
        # 检查确认模式
        print(f"ℹ️  Confirm Mode: {config.processing.confirm_mode}")
        
        return True
        
    except Exception as e:
        print(f"❌ 配置加载失败: {e}")
        return False

def check_redis():
    """检查 Redis 连接"""
    print("\n" + "=" * 60)
    print("4. Redis 连接检查")
    print("=" * 60)
    
    try:
        import asyncio
        from core.config import get_config
        
        config = get_config()
        
        async def test_redis():
            try:
                import redis.asyncio as redis
                r = redis.from_url(config.queue.redis_url)
                await r.ping()
                await r.close()
                return True
            except Exception as e:
                return str(e)
        
        result = asyncio.run(test_redis())
        
        if result is True:
            print("✅ Redis 连接成功")
            return True
        else:
            print(f"⚠️  Redis 连接失败: {result}")
            print("   将使用本地内存队列（重启后数据丢失）")
            return True  # 不是致命错误，有降级方案
            
    except Exception as e:
        print(f"⚠️  Redis 检查失败: {e}")
        return True

def check_ollama():
    """检查 Ollama"""
    print("\n" + "=" * 60)
    print("5. Ollama 连接检查")
    print("=" * 60)
    
    try:
        import asyncio
        from core.llm.ollama_client import OllamaClient
        
        async def test_ollama():
            client = OllamaClient()
            try:
                healthy = await client.health_check()
                return healthy
            finally:
                await client.close()
        
        result = asyncio.run(test_ollama())
        
        if result:
            print("✅ Ollama 服务正常")
        else:
            print("⚠️  Ollama 服务未响应（将使用 fallback）")
        
        return True
        
    except Exception as e:
        print(f"⚠️  Ollama 检查失败: {e}")
        print("   确保 Ollama 已安装: https://ollama.ai")
        return True  # 不是致命错误，有 fallback

def check_github_api():
    """检查 GitHub API"""
    print("\n" + "=" * 60)
    print("6. GitHub API 检查")
    print("=" * 60)
    
    try:
        import asyncio
        from core.github_api import get_github_client
        
        async def test_github():
            client = get_github_client()
            
            # 检查认证方式
            if client.credentials.token:
                print("✅ 使用 PAT 认证")
            elif client.credentials.app_id:
                print("✅ 使用 GitHub App 认证")
            else:
                print("❌ 未配置 GitHub 认证")
                return False
            
            # 尝试 API 调用（可选）
            # 使用公开的 octocat/Hello-World 仓库测试
            try:
                repo = await client.get_repo("octocat", "Hello-World")
                print(f"✅ API 调用成功: {repo.get('full_name', 'unknown')}")
                return True
            except Exception as e:
                print(f"⚠️  API 测试调用失败: {e}")
                print("   可能是网络问题或 Token 权限不足")
                return True  # 认证配置正确即可
            finally:
                await client.close()
        
        return asyncio.run(test_github())
        
    except Exception as e:
        print(f"❌ GitHub API 检查失败: {e}")
        return False

def check_struct():
    """检查项目结构"""
    print("\n" + "=" * 60)
    print("7. 项目结构检查")
    print("=" * 60)
    
    required_files = [
        "main.py",
        "requirements.txt",
        "core/__init__.py",
        "core/config.py",
        "core/queue/manager.py",
        "core/queue/worker.py",
        "core/llm/manager.py",
        "core/github_api/client.py",
        "services/processor.py",
        "services/webhook_server.py",
    ]
    
    all_ok = True
    base = os.path.dirname(os.path.abspath(__file__))
    
    for file in required_files:
        path = os.path.join(base, file)
        if os.path.exists(path):
            print(f"✅ {file}")
        else:
            print(f"❌ {file} - 缺失")
            all_ok = False
    
    return all_ok

def main():
    """主函数"""
    print("\n" + "=" * 60)
    print("   GitHub Agent V3 - 诊断工具")
    print("=" * 60 + "\n")
    
    checks = [
        ("Python 版本", check_python_version),
        ("依赖安装", check_dependencies),
        ("配置加载", check_config),
        ("Redis 连接", check_redis),
        ("Ollama 服务", check_ollama),
        ("GitHub API", check_github_api),
        ("项目结构", check_struct),
    ]
    
    results = []
    for name, check_fn in checks:
        try:
            result = check_fn()
            results.append((name, result))
        except Exception as e:
            print(f"\n❌ {name} 检查异常: {e}")
            results.append((name, False))
    
    # 总结
    print("\n" + "=" * 60)
    print("诊断总结")
    print("=" * 60)
    
    passed = sum(1 for _, r in results if r)
    total = len(results)
    
    for name, result in results:
        status = "✅" if result else "❌"
        print(f"{status} {name}")
    
    print(f"\n总计: {passed}/{total} 项通过")
    
    if passed == total:
        print("\n🎉 所有检查通过！可以启动服务:")
        print("   python main.py")
    else:
        print("\n⚠️  部分检查未通过，请根据提示修复后再启动")
    
    return passed == total

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)