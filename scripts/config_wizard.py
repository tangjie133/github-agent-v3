#!/usr/bin/env python3
"""
GitHub Agent V3 - 交互式配置向导
生成并管理 .env 配置文件
"""

import os
import re
import sys
import secrets
from pathlib import Path
from typing import Optional, Dict, Any, List, Tuple

# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    END = '\033[0m'

def print_header(text):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE} {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_success(text):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_warning(text):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_error(text):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_info(text):
    print(f"{Colors.CYAN}ℹ️  {text}{Colors.END}")

def print_section(text):
    print(f"\n{Colors.BOLD}{Colors.CYAN}▶ {text}{Colors.END}")

def input_required(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    """获取必填输入"""
    while True:
        if default:
            display = f" [{default}]" if not secret else " [*****]"
        else:
            display = ""
        
        if secret:
            import getpass
            value = getpass.getpass(f"{prompt}{display}: ")
        else:
            value = input(f"{prompt}{display}: ").strip()
        
        if value:
            return value
        elif default:
            return default
        else:
            print_error("此项为必填项，请重新输入")

def input_optional(prompt: str, default: Optional[str] = None) -> Optional[str]:
    """获取可选输入"""
    if default:
        value = input(f"{prompt} [{default}]: ").strip()
    else:
        value = input(f"{prompt} [可选]: ").strip()
    return value if value else default

def input_confirm(prompt: str, default: bool = False) -> bool:
    """确认输入"""
    default_str = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{default_str}]: ").strip().lower()
    if not value:
        return default
    return value in ('y', 'yes', '是')

def input_select(prompt: str, options: List[str], default: Optional[str] = None) -> str:
    """选择输入"""
    print(f"\n{prompt}:")
    for i, opt in enumerate(options, 1):
        marker = " (默认)" if opt == default else ""
        print(f"  {i}. {opt}{marker}")
    
    while True:
        if default:
            value = input(f"请选择 [1-{len(options)}] (默认: {options.index(default)+1}): ").strip()
            if not value:
                return default
        else:
            value = input(f"请选择 [1-{len(options)}]: ").strip()
        
        try:
            idx = int(value) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            if value in options:
                return value
        
        print_error("无效的选择，请重试")

def input_int(prompt: str, default: int, min_val: int, max_val: int) -> int:
    """整数输入"""
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            val = int(value)
            if min_val <= val <= max_val:
                return val
            print_error(f"请输入 {min_val} 到 {max_val} 之间的整数")
        except ValueError:
            print_error("请输入有效的整数")

def input_float(prompt: str, default: float, min_val: float, max_val: float) -> float:
    """浮点数输入"""
    while True:
        value = input(f"{prompt} [{default}]: ").strip()
        if not value:
            return default
        try:
            val = float(value)
            if min_val <= val <= max_val:
                return val
            print_error(f"请输入 {min_val} 到 {max_val} 之间的数值")
        except ValueError:
            print_error("请输入有效的数值")

def validate_github_token(token: str) -> Tuple[bool, str]:
    """验证 GitHub Token 格式"""
    if not token:
        return False, "Token 不能为空"
    if not (token.startswith('ghp_') or token.startswith('github_pat_')):
        return False, "Token 格式不正确（应以 ghp_ 或 github_pat_ 开头）"
    return True, "格式正确"

def test_github_connection(token: str) -> Tuple[bool, str]:
    """测试 GitHub API 连接"""
    try:
        import urllib.request
        import json
        
        req = urllib.request.Request(
            'https://api.github.com/user',
            headers={'Authorization': f'Bearer {token}', 'Accept': 'application/vnd.github.v3+json'}
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                data = json.loads(response.read().decode())
                return True, data.get('login', 'Unknown')
            else:
                return False, f"HTTP {response.status}"
    except Exception as e:
        return False, str(e)

def generate_webhook_secret() -> str:
    """生成随机 Webhook Secret"""
    return secrets.token_urlsafe(32)

def load_existing_config() -> Dict[str, str]:
    """加载现有配置"""
    env_file = Path('.env')
    config = {}
    
    if env_file.exists():
        content = env_file.read_text()
        for line in content.split('\n'):
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                config[key.strip()] = value.strip().strip('"').strip("'")
    
    return config

def save_config(config: Dict[str, Any]):
    """保存配置到 .env 文件"""
    env_file = Path('.env')
    
    lines = []
    lines.append("# GitHub Agent V3 配置文件")
    lines.append("# 生成时间: " + __import__('datetime').datetime.now().isoformat())
    lines.append("")
    
    # 按类别组织配置
    sections = [
        ("GitHub 认证", [
            ("GITHUB_TOKEN", "GitHub Personal Access Token"),
            ("GITHUB_WEBHOOK_SECRET", "Webhook 签名密钥"),
        ]),
        ("GitHub App 认证（可选）", [
            ("GITHUB_AGENT_GITHUB__APP_ID", "GitHub App ID"),
            ("GITHUB_AGENT_GITHUB__PRIVATE_KEY_PATH", "私钥文件路径"),
        ]),
        ("服务配置", [
            ("GITHUB_AGENT_STORAGE__DATADIR", "数据存储目录"),
            ("GITHUB_AGENT_QUEUE__REDIS_URL", "Redis 连接 URL（可选）"),
        ]),
        ("LLM 配置", [
            ("GITHUB_AGENT_LLM__OLLAMA_HOST", "Ollama 服务地址"),
            ("GITHUB_AGENT_LLM__OLLAMA_MODEL_INTENT", "意图识别模型"),
            ("GITHUB_AGENT_LLM__OLLAMA_MODEL_CODE", "代码生成模型"),
            ("GITHUB_AGENT_LLM__OLLAMA_MODEL_ANSWER", "回复生成模型"),
            ("GITHUB_AGENT_LLM__OLLAMA_TIMEOUT", "Ollama 超时时间（秒）"),
            ("GITHUB_AGENT_LLM__PRIMARY_PROVIDER", "主 LLM 提供商"),
            ("GITHUB_AGENT_LLM__FALLBACK_PROVIDER", "备用 LLM 提供商"),
        ]),
        ("OpenClaw 配置", [
            ("OPENCLAW_API_KEY", "OpenClaw API Key（可选）"),
            ("GITHUB_AGENT_LLM__OPENCLAW_URL", "OpenClaw 服务地址"),
            ("GITHUB_AGENT_LLM__OPENCLAW_ENABLED", "是否启用 OpenClaw"),
        ]),
        ("处理配置", [
            ("GITHUB_AGENT_PROCESSING__CONFIRM_MODE", "确认模式 (manual/auto/smart)"),
            ("GITHUB_AGENT_PROCESSING__AUTO_CONFIRM_THRESHOLD", "自动确认阈值 (0-1)"),
            ("GITHUB_AGENT_PROCESSING__CONFIRM_TIMEOUT_HOURS", "确认超时时间（小时）"),
        ]),
        ("通知配置", [
            ("GITHUB_AGENT_NOTIFICATION__SMTP_HOST", "SMTP 服务器地址"),
            ("GITHUB_AGENT_NOTIFICATION__SMTP_PORT", "SMTP 端口"),
            ("GITHUB_AGENT_NOTIFICATION__SMTP_USER", "SMTP 用户名"),
            ("GITHUB_AGENT_NOTIFICATION__SMTP_PASSWORD", "SMTP 密码"),
            ("GITHUB_AGENT_NOTIFICATION__ADMIN_EMAIL", "管理员邮箱"),
            ("GITHUB_AGENT_NOTIFICATION__NOTIFY_ADMIN_ON_FAILURE", "失败时通知管理员"),
        ]),
        ("日志配置", [
            ("GITHUB_AGENT_LOGGING__LEVEL", "日志级别"),
            ("GITHUB_AGENT_LOGGING__FORMAT", "日志格式 (json/text)"),
            ("GITHUB_AGENT_LOGGING__DEBUG", "调试模式 (true/false)"),
        ]),
        ("知识库配置", [
            ("GITHUB_AGENT_KNOWLEDGE_BASE__ENABLED", "启用知识库 (true/false)"),
            ("GITHUB_AGENT_KNOWLEDGE_BASE__SERVICE_URL", "知识库服务地址"),
            ("GITHUB_AGENT_KNOWLEDGE_BASE__EMBEDDING_MODEL", "嵌入模型"),
        ]),
    ]
    
    for section_name, keys in sections:
        section_lines = []
        for key, desc in keys:
            if key in config and config[key] is not None:
                section_lines.append(f"# {desc}")
                section_lines.append(f"{key}={config[key]}")
        
        if section_lines:
            lines.append(f"# ========== {section_name} ==========")
            lines.extend(section_lines)
            lines.append("")
    
    # 写入文件
    env_file.write_text('\n'.join(lines))
    
    # 设置权限（仅所有者可读写）
    os.chmod(env_file, 0o600)

def run_wizard():
    """运行配置向导"""
    print_header("GitHub Agent V3 配置向导")
    print_info("本向导将帮助你配置 GitHub Agent V3 的所有必要参数")
    print_info("带 * 的为必填项，其他为可选项（可直接回车使用默认值）\n")
    
    # 检查现有配置
    existing = load_existing_config()
    if existing:
        print_warning("检测到现有配置文件 (.env)")
        choice = input("选择操作: [K]eep保留 / [U]pdate更新 / [O]verwrite重写: ").strip().upper()
        if choice == 'K':
            print_info("保持现有配置，退出向导")
            return
        elif choice == 'O':
            existing = {}
            print_info("将创建全新配置")
        else:
            print_info("将更新现有配置")
    
    config = {}
    
    # ========== GitHub 认证 ==========
    print_header("步骤 1/6: GitHub 认证")
    
    print_info("需要 GitHub Personal Access Token (classic)")
    print("获取方式: GitHub → Settings → Developer settings → Personal access tokens → Tokens (classic)")
    print("所需权限: repo, workflow, read:user")
    print("")
    
    while True:
        token = input_required(
            "* GitHub Token",
            default=existing.get('GITHUB_TOKEN'),
            secret=True
        )
        
        valid, msg = validate_github_token(token)
        if not valid:
            print_error(f"Token 验证失败: {msg}")
            continue
        
        print_info("正在测试 GitHub 连接...")
        success, username = test_github_connection(token)
        
        if success:
            print_success(f"GitHub 连接成功！用户: {username}")
            config['GITHUB_TOKEN'] = token
            break
        else:
            print_error(f"GitHub 连接失败: {username}")
            retry = input("是否重试? [Y/n]: ").strip().lower()
            if retry == 'n':
                print_warning("跳过验证，继续配置")
                config['GITHUB_TOKEN'] = token
                break
    
    # Webhook Secret
    if 'GITHUB_WEBHOOK_SECRET' in existing:
        keep = input_confirm("是否保留现有的 Webhook Secret?", default=True)
        if keep:
            config['GITHUB_WEBHOOK_SECRET'] = existing['GITHUB_WEBHOOK_SECRET']
        else:
            generate = input_confirm("自动生成新的 Webhook Secret?", default=True)
            if generate:
                config['GITHUB_WEBHOOK_SECRET'] = generate_webhook_secret()
                print_success("已生成随机 Webhook Secret")
            else:
                config['GITHUB_WEBHOOK_SECRET'] = input_required("* Webhook Secret", secret=True)
    else:
        generate = input_confirm("自动生成 Webhook Secret?", default=True)
        if generate:
            config['GITHUB_WEBHOOK_SECRET'] = generate_webhook_secret()
            print_success("已生成随机 Webhook Secret")
        else:
            config['GITHUB_WEBHOOK_SECRET'] = input_required("* Webhook Secret", secret=True)
    
    # GitHub App（可选）
    print_section("GitHub App 认证（可选，用于团队部署）")
    use_app = input_confirm("是否配置 GitHub App 认证?")
    if use_app:
        app_id = input_optional("GitHub App ID")
        if app_id:
            config['GITHUB_AGENT_GITHUB__APP_ID'] = app_id
            key_path = input_required("私钥文件路径")
            config['GITHUB_AGENT_GITHUB__PRIVATE_KEY_PATH'] = key_path
    
    # ========== 服务配置 ==========
    print_header("步骤 2/6: 服务配置")
    
    # 数据目录
    default_datadir = existing.get('GITHUB_AGENT_STORAGE__DATADIR', str(Path.home() / "github-agent-data"))
    datadir = input_optional("数据存储目录", default=default_datadir)
    config['GITHUB_AGENT_STORAGE__DATADIR'] = datadir or default_datadir
    
    # Redis
    use_redis = input_confirm("是否使用 Redis 队列?（否则使用内存队列）")
    if use_redis:
        redis_url = input_optional("Redis URL", default="redis://localhost:6379/0")
        config['GITHUB_AGENT_QUEUE__REDIS_URL'] = redis_url or "redis://localhost:6379/0"
    
    # ========== LLM 配置 ==========
    print_header("步骤 3/6: LLM 配置")
    
    print_info("支持多级 Fallback: Ollama → OpenClaw → Template")
    print("")
    
    # Ollama 配置
    ollama_host = input_optional(
        "Ollama 服务地址",
        default=existing.get('GITHUB_AGENT_LLM__OLLAMA_HOST', 'http://localhost:11434')
    )
    config['GITHUB_AGENT_LLM__OLLAMA_HOST'] = ollama_host or "http://localhost:11434"
    
    # 模型配置
    print_section("Ollama 模型配置")
    
    intent_model = input_optional(
        "意图识别模型",
        default=existing.get('GITHUB_AGENT_LLM__OLLAMA_MODEL_INTENT', 'qwen3:8b')
    )
    config['GITHUB_AGENT_LLM__OLLAMA_MODEL_INTENT'] = intent_model or "qwen3:8b"
    
    code_model = input_optional(
        "代码生成模型",
        default=existing.get('GITHUB_AGENT_LLM__OLLAMA_MODEL_CODE', 'qwen3-coder:30b')
    )
    config['GITHUB_AGENT_LLM__OLLAMA_MODEL_CODE'] = code_model or "qwen3-coder:30b"
    
    answer_model = input_optional(
        "回复生成模型",
        default=existing.get('GITHUB_AGENT_LLM__OLLAMA_MODEL_ANSWER', 'qwen3-coder:14b')
    )
    config['GITHUB_AGENT_LLM__OLLAMA_MODEL_ANSWER'] = answer_model or "qwen3-coder:14b"
    
    ollama_timeout = input_int(
        "Ollama 超时时间（秒）",
        default=int(existing.get('GITHUB_AGENT_LLM__OLLAMA_TIMEOUT', '300')),
        min_val=10,
        max_val=600
    )
    config['GITHUB_AGENT_LLM__OLLAMA_TIMEOUT'] = str(ollama_timeout)
    
    # 主/备用提供商
    print_section("LLM 提供商选择")
    
    primary = input_select(
        "主 LLM 提供商",
        options=["ollama", "openclaw"],
        default="ollama"
    )
    config['GITHUB_AGENT_LLM__PRIMARY_PROVIDER'] = primary
    
    fallback = input_select(
        "备用 LLM 提供商",
        options=["ollama", "openclaw", "none"],
        default="openclaw"
    )
    config['GITHUB_AGENT_LLM__FALLBACK_PROVIDER'] = fallback
    
    # OpenClaw 配置
    if primary == "openclaw" or fallback == "openclaw":
        print_section("OpenClaw 配置")
        
        use_openclaw = input_confirm("是否启用 OpenClaw 作为 Fallback?", default=True)
        config['GITHUB_AGENT_LLM__OPENCLAW_ENABLED'] = str(use_openclaw).lower()
        
        if use_openclaw:
            openclaw_key = input_optional("OpenClaw API Key（可选）", secret=True)
            if openclaw_key:
                config['OPENCLAW_API_KEY'] = openclaw_key
            
            openclaw_url = input_optional(
                "OpenClaw 服务地址",
                default="http://localhost:3000"
            )
            config['GITHUB_AGENT_LLM__OPENCLAW_URL'] = openclaw_url or "http://localhost:3000"
    
    # ========== 处理配置 ==========
    print_header("步骤 4/6: 处理配置")
    
    confirm_mode = input_select(
        "修复确认模式",
        options=["manual", "auto", "smart"],
        default=existing.get('GITHUB_AGENT_PROCESSING__CONFIRM_MODE', 'manual')
    )
    config['GITHUB_AGENT_PROCESSING__CONFIRM_MODE'] = confirm_mode
    
    if confirm_mode in ["auto", "smart"]:
        threshold = input_float(
            "自动确认阈值（0-1，越高越严格）",
            default=float(existing.get('GITHUB_AGENT_PROCESSING__AUTO_CONFIRM_THRESHOLD', '0.8')),
            min_val=0.0,
            max_val=1.0
        )
        config['GITHUB_AGENT_PROCESSING__AUTO_CONFIRM_THRESHOLD'] = str(threshold)
    
    timeout_hours = input_int(
        "确认超时时间（小时）",
        default=int(existing.get('GITHUB_AGENT_PROCESSING__CONFIRM_TIMEOUT_HOURS', '168')),
        min_val=1,
        max_val=720
    )
    config['GITHUB_AGENT_PROCESSING__CONFIRM_TIMEOUT_HOURS'] = str(timeout_hours)
    
    # ========== 通知配置 ==========
    print_header("步骤 5/6: 邮件通知（可选）")
    
    use_email = input_confirm("是否配置邮件通知?")
    if use_email:
        smtp_host = input_optional(
            "SMTP 服务器",
            default=existing.get('GITHUB_AGENT_NOTIFICATION__SMTP_HOST', 'smtp.gmail.com')
        )
        config['GITHUB_AGENT_NOTIFICATION__SMTP_HOST'] = smtp_host or "smtp.gmail.com"
        
        smtp_port = input_int(
            "SMTP 端口",
            default=int(existing.get('GITHUB_AGENT_NOTIFICATION__SMTP_PORT', '587')),
            min_val=1,
            max_val=65535
        )
        config['GITHUB_AGENT_NOTIFICATION__SMTP_PORT'] = str(smtp_port)
        
        smtp_user = input_optional(
            "SMTP 用户名/邮箱",
            default=existing.get('GITHUB_AGENT_NOTIFICATION__SMTP_USER')
        )
        if smtp_user:
            config['GITHUB_AGENT_NOTIFICATION__SMTP_USER'] = smtp_user
            
            smtp_pass = input_required("SMTP 密码/授权码", secret=True)
            config['GITHUB_AGENT_NOTIFICATION__SMTP_PASSWORD'] = smtp_pass
        
        admin_email = input_optional(
            "管理员邮箱（接收通知）",
            default=existing.get('GITHUB_AGENT_NOTIFICATION__ADMIN_EMAIL')
        )
        if admin_email:
            config['GITHUB_AGENT_NOTIFICATION__ADMIN_EMAIL'] = admin_email
            config['GITHUB_AGENT_NOTIFICATION__NOTIFY_ADMIN_ON_FAILURE'] = "true"
    
    # ========== 日志配置 ==========
    print_header("步骤 6/6: 日志配置")
    
    log_level = input_select(
        "日志级别",
        options=["DEBUG", "INFO", "WARNING", "ERROR"],
        default=existing.get('GITHUB_AGENT_LOGGING__LEVEL', 'INFO')
    )
    config['GITHUB_AGENT_LOGGING__LEVEL'] = log_level
    
    log_format = input_select(
        "日志格式",
        options=["json", "text"],
        default=existing.get('GITHUB_AGENT_LOGGING__FORMAT', 'json')
    )
    config['GITHUB_AGENT_LOGGING__FORMAT'] = log_format
    
    debug_mode = input_confirm("启用调试模式?（详细日志）", default=False)
    config['GITHUB_AGENT_LOGGING__DEBUG'] = str(debug_mode).lower()
    
    # 知识库配置
    print_section("知识库配置")
    kb_enabled = input_confirm("启用知识库?", default=True)
    config['GITHUB_AGENT_KNOWLEDGE_BASE__ENABLED'] = str(kb_enabled).lower()
    
    if kb_enabled:
        kb_url = input_optional(
            "知识库服务地址",
            default=existing.get('GITHUB_AGENT_KNOWLEDGE_BASE__SERVICE_URL', 'http://localhost:8000')
        )
        config['GITHUB_AGENT_KNOWLEDGE_BASE__SERVICE_URL'] = kb_url or "http://localhost:8000"
        
        embed_model = input_optional(
            "嵌入模型",
            default=existing.get('GITHUB_AGENT_KNOWLEDGE_BASE__EMBEDDING_MODEL', 'nomic-embed-text')
        )
        config['GITHUB_AGENT_KNOWLEDGE_BASE__EMBEDDING_MODEL'] = embed_model or "nomic-embed-text"
    
    # 保存配置
    print_header("保存配置")
    
    try:
        save_config(config)
        print_success(f"配置已保存到: {Path('.env').absolute()}")
        print_info("文件权限已设置为 600（仅所有者可读写）")
    except Exception as e:
        print_error(f"保存配置失败: {e}")
        sys.exit(1)
    
    # 显示配置摘要
    print_header("配置摘要")
    print(f"  GitHub Token: {'*' * 20} (已隐藏)")
    print(f"  Webhook Secret: {'*' * 20} (已隐藏)")
    print(f"  数据目录: {config.get('GITHUB_AGENT_STORAGE__DATADIR', '默认')}")
    print(f"  Redis: {'已配置' if 'GITHUB_AGENT_QUEUE__REDIS_URL' in config else '使用内存队列'}")
    print(f"  Ollama: {config.get('GITHUB_AGENT_LLM__OLLAMA_HOST', '默认')}")
    print(f"  主 LLM: {config.get('GITHUB_AGENT_LLM__PRIMARY_PROVIDER', 'ollama')}")
    print(f"  备用 LLM: {config.get('GITHUB_AGENT_LLM__FALLBACK_PROVIDER', 'openclaw')}")
    print(f"  OpenClaw: {'已配置' if 'OPENCLAW_API_KEY' in config else '未配置 API Key'}")
    print(f"  确认模式: {config.get('GITHUB_AGENT_PROCESSING__CONFIRM_MODE', 'manual')}")
    print(f"  日志级别: {config.get('GITHUB_AGENT_LOGGING__LEVEL', 'INFO')}")
    print(f"  知识库: {'启用' if config.get('GITHUB_AGENT_KNOWLEDGE_BASE__ENABLED') == 'true' else '禁用'}")
    
    print("")
    print_success("配置向导完成！")
    print("")
    print("📋 下一步:")
    print("   1. 检查配置: cat .env")
    print("   2. 验证配置: make config-validate")
    print("   3. 启动服务: make dev")
    print("")
    print_info("如需修改配置，重新运行: make config")

def show_config():
    """显示当前配置（隐藏敏感信息）"""
    env_file = Path('.env')
    
    if not env_file.exists():
        print_error("配置文件 .env 不存在")
        print_info("运行 'make config' 创建配置")
        return
    
    print_header("当前配置")
    
    content = env_file.read_text()
    for line in content.split('\n'):
        line = line.strip()
        if not line:
            continue
        
        if line.startswith('#'):
            # 节标题美化
            if '===' in line:
                section = line.replace('#', '').replace('=', '').strip()
                print(f"\n{Colors.BOLD}{Colors.CYAN}{section}{Colors.END}")
            else:
                print(f"  {Colors.CYAN}{line}{Colors.END}")
            continue
        
        if '=' in line:
            key, value = line.split('=', 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            
            # 隐藏敏感信息
            if any(s in key.upper() for s in ['TOKEN', 'SECRET', 'KEY', 'PASSWORD']):
                if value:
                    value = '*' * min(len(value), 20)
            
            # 对齐显示
            print(f"    {key:50s} = {value}")

def validate_config():
    """验证配置完整性"""
    print_header("配置验证")
    
    env_file = Path('.env')
    if not env_file.exists():
        print_error("配置文件 .env 不存在")
        return False
    
    config = load_existing_config()
    errors = []
    warnings = []
    
    # 必需项检查
    if not config.get('GITHUB_TOKEN'):
        errors.append("缺少 GITHUB_TOKEN")
    
    if not config.get('GITHUB_WEBHOOK_SECRET'):
        errors.append("缺少 GITHUB_WEBHOOK_SECRET")
    
    # 连接测试
    if 'GITHUB_TOKEN' in config and config['GITHUB_TOKEN']:
        print_info("测试 GitHub 连接...")
        success, msg = test_github_connection(config['GITHUB_TOKEN'])
        if success:
            print_success(f"GitHub 连接正常: {msg}")
        else:
            errors.append(f"GitHub 连接失败: {msg}")
    
    # Ollama 测试
    ollama_host = config.get('GITHUB_AGENT_LLM__OLLAMA_HOST', 'http://localhost:11434')
    print_info(f"测试 Ollama 连接 ({ollama_host})...")
    try:
        import urllib.request
        req = urllib.request.Request(f"{ollama_host}/api/tags", timeout=5)
        with urllib.request.urlopen(req) as resp:
            if resp.status == 200:
                print_success("Ollama 连接正常")
            else:
                warnings.append(f"Ollama 返回异常状态: {resp.status}")
    except Exception as e:
        warnings.append(f"Ollama 连接失败: {e}")
    
    # 数据目录检查
    datadir = config.get('GITHUB_AGENT_STORAGE__DATADIR', str(Path.home() / 'github-agent-data'))
    print_info(f"检查数据目录 ({datadir})...")
    try:
        Path(datadir).mkdir(parents=True, exist_ok=True)
        test_file = Path(datadir) / ".write_test"
        test_file.touch()
        test_file.unlink()
        print_success("数据目录可读写")
    except Exception as e:
        errors.append(f"数据目录不可写: {e}")
    
    # 结果输出
    print("")
    if errors:
        print_error(f"发现 {len(errors)} 个错误:")
        for e in errors:
            print(f"  ❌ {e}")
    
    if warnings:
        print_warning(f"发现 {len(warnings)} 个警告:")
        for w in warnings:
            print(f"  ⚠️  {w}")
    
    if not errors and not warnings:
        print_success("配置验证通过！所有检查项均正常")
        return True
    
    return len(errors) == 0

if __name__ == '__main__':
    import argparse
    
    parser = argparse.ArgumentParser(description='GitHub Agent V3 配置管理')
    parser.add_argument('action', choices=['wizard', 'show', 'validate'], 
                       default='wizard', nargs='?',
                       help='操作: wizard(配置向导), show(显示配置), validate(验证配置)')
    
    args = parser.parse_args()
    
    if args.action == 'wizard':
        run_wizard()
    elif args.action == 'show':
        show_config()
    elif args.action == 'validate':
        validate_config()
