#!/usr/bin/env python3
"""
GitHub Agent V3 - 交互式配置向导（目录导航版）
支持按需修改，保留已有配置
"""

import os
import sys
import secrets
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

# 颜色输出
class Colors:
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    RED = '\033[91m'
    BLUE = '\033[94m'
    CYAN = '\033[96m'
    BOLD = '\033[1m'
    DIM = '\033[2m'
    END = '\033[0m'

def print_header(text: str):
    print(f"\n{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE} {text}{Colors.END}")
    print(f"{Colors.BOLD}{Colors.BLUE}{'='*60}{Colors.END}\n")

def print_section(text: str):
    print(f"\n{Colors.BOLD}{Colors.CYAN}▶ {text}{Colors.END}")

def print_success(text: str):
    print(f"{Colors.GREEN}✅ {text}{Colors.END}")

def print_warning(text: str):
    print(f"{Colors.YELLOW}⚠️  {text}{Colors.END}")

def print_error(text: str):
    print(f"{Colors.RED}❌ {text}{Colors.END}")

def print_info(text: str):
    print(f"{Colors.CYAN}ℹ️  {text}{Colors.END}")

def print_menu_item(key: str, desc: str, current: str = ""):
    """打印菜单项"""
    current_str = f" {Colors.DIM}(当前: {current}){Colors.END}" if current else ""
    print(f"  [{Colors.BOLD}{Colors.CYAN}{key}{Colors.END}] {desc}{current_str}")

def print_config_item(name: str, value: str, desc: str = ""):
    """打印配置项"""
    # 隐藏敏感信息
    display_value = value
    if any(s in name.upper() for s in ['TOKEN', 'SECRET', 'KEY', 'PASSWORD']) and value:
        display_value = '*' * min(len(value), 20)
    
    desc_str = f" {Colors.DIM}# {desc}{Colors.END}" if desc else ""
    print(f"    {name:45s} = {Colors.GREEN}{display_value}{Colors.END}{desc_str}")

@dataclass
class ConfigItem:
    """配置项定义"""
    key: str
    description: str
    category: str
    default: Any = None
    secret: bool = False
    options: Optional[List[str]] = None
    input_type: str = "str"

# ============ 配置项定义（与之前相同） ============
CONFIG_ITEMS = [
    # GitHub 认证
    ConfigItem("GITHUB_TOKEN", "GitHub Personal Access Token", "GitHub 认证", default=None, secret=True),
    ConfigItem("GITHUB_WEBHOOK_SECRET", "Webhook 签名密钥", "GitHub 认证", default=None, secret=True),
    ConfigItem("GITHUB_APP_ID", "GitHub App ID", "GitHub 认证", default=""),
    ConfigItem("GITHUB_APP_PRIVATE_KEY", "GitHub App 私钥内容", "GitHub 认证", default="", secret=True),
    ConfigItem("GITHUB_APP_PRIVATE_KEY_PATH", "GitHub App 私钥文件路径", "GitHub 认证", default=""),
    
    # 目录配置
    ConfigItem("GITHUB_AGENT_STORAGE__DATADIR", "数据存储目录", "目录配置", default="~/github-agent-data"),
    ConfigItem("GITHUB_AGENT_WORKDIR", "工作目录（代码检出）", "目录配置", default="/tmp/github-agent-repos"),
    ConfigItem("GITHUB_AGENT_STATEDIR", "状态目录（知识库服务）", "目录配置", default="/tmp/github-agent-state"),
    
    # Webhook 配置
    ConfigItem("GITHUB_AGENT_WEBHOOK__HOST", "Webhook 监听地址", "Webhook 配置", default="0.0.0.0"),
    ConfigItem("GITHUB_AGENT_WEBHOOK__PORT", "Webhook 监听端口", "Webhook 配置", default=8000, input_type="int"),
    
    # 队列配置
    ConfigItem("GITHUB_AGENT_QUEUE__REDIS_URL", "Redis 连接 URL（可选）", "队列配置", default=""),
    ConfigItem("GITHUB_AGENT_QUEUE__WORKERS", "工作进程数", "队列配置", default=4, input_type="int"),
    
    # LLM 配置
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_HOST", "Ollama 服务地址", "LLM 配置", default="http://localhost:11434"),
    ConfigItem("OLLAMA_MODEL", "默认 Ollama 模型", "LLM 配置", default="qwen3-coder:30b"),
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_MODEL_INTENT", "意图识别模型", "LLM 配置", default="qwen3:8b"),
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_MODEL_CODE", "代码生成模型", "LLM 配置", default="qwen3-coder:30b"),
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_MODEL_ANSWER", "回复生成模型", "LLM 配置", default="qwen3-coder:14b"),
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_TIMEOUT", "Ollama 超时时间（秒）", "LLM 配置", default=300, input_type="int"),
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_MAX_CONCURRENT", "Ollama 最大并发数", "LLM 配置", default=1, input_type="int"),
    ConfigItem("GITHUB_AGENT_LLM__OLLAMA_EMBEDDING_MODEL", "嵌入模型", "LLM 配置", default="nomic-embed-text"),
    ConfigItem("GITHUB_AGENT_LLM__PRIMARY_PROVIDER", "主 LLM 提供商", "LLM 配置", default="ollama", options=["ollama", "openclaw"]),
    ConfigItem("GITHUB_AGENT_LLM__FALLBACK_PROVIDER", "备用 LLM 提供商", "LLM 配置", default="openclaw", options=["ollama", "openclaw", "none"]),
    
    # OpenClaw 配置
    ConfigItem("OPENCLAW_API_KEY", "OpenClaw API Key", "OpenClaw 配置", default="", secret=True),
    ConfigItem("GITHUB_AGENT_LLM__OPENCLAW_URL", "OpenClaw 服务地址", "OpenClaw 配置", default="http://localhost:3000"),
    ConfigItem("GITHUB_AGENT_LLM__OPENCLAW_ENABLED", "启用 OpenClaw", "OpenClaw 配置", default=True, input_type="bool"),
    ConfigItem("GITHUB_AGENT_LLM__OPENCLAW_TIMEOUT", "OpenClaw 超时时间（秒）", "OpenClaw 配置", default=60, input_type="int"),
    ConfigItem("OPENCLAW_API_URL", "OpenClaw API URL", "OpenClaw 配置", default="http://localhost:3000/api/v1"),
    
    # 处理配置
    ConfigItem("GITHUB_AGENT_PROCESSING__CONFIRM_MODE", "修复确认模式", "处理配置", default="manual", options=["manual", "auto", "smart"]),
    ConfigItem("GITHUB_AGENT_PROCESSING__AUTO_CONFIRM_THRESHOLD", "自动确认阈值（0-1）", "处理配置", default=0.8, input_type="float"),
    ConfigItem("GITHUB_AGENT_PROCESSING__MAX_RETRIES", "最大重试次数", "处理配置", default=3, input_type="int"),
    ConfigItem("GITHUB_AGENT_PROCESSING__RETRY_DELAY", "重试延迟（秒）", "处理配置", default=1.0, input_type="float"),
    ConfigItem("GITHUB_AGENT_PROCESSING__RETRY_BACKOFF", "重试退避系数", "处理配置", default=2.0, input_type="float"),
    
    # 通知配置
    ConfigItem("GITHUB_AGENT_NOTIFICATION__SMTP_HOST", "SMTP 服务器", "通知配置", default="smtp.gmail.com"),
    ConfigItem("GITHUB_AGENT_NOTIFICATION__SMTP_PORT", "SMTP 端口", "通知配置", default=587, input_type="int"),
    ConfigItem("GITHUB_AGENT_NOTIFICATION__SMTP_USER", "SMTP 用户名", "通知配置", default=""),
    ConfigItem("GITHUB_AGENT_NOTIFICATION__SMTP_PASSWORD", "SMTP 密码", "通知配置", default="", secret=True),
    ConfigItem("GITHUB_AGENT_NOTIFICATION__ADMIN_EMAIL", "管理员邮箱", "通知配置", default=""),
    ConfigItem("GITHUB_AGENT_NOTIFICATION__NOTIFY_ADMIN_ON_FAILURE", "失败时通知管理员", "通知配置", default=True, input_type="bool"),
    
    # 日志配置
    ConfigItem("LOG_LEVEL", "日志级别", "日志配置", default="INFO", options=["DEBUG", "INFO", "WARNING", "ERROR"]),
    ConfigItem("GITHUB_AGENT_LOGGING__JSON_FILE", "输出 JSON 格式日志文件", "日志配置", default=True, input_type="bool"),
    ConfigItem("GITHUB_AGENT_LOGGING__TEXT_FILE", "输出文本格式日志文件", "日志配置", default=True, input_type="bool"),
    
    # 调试配置
    ConfigItem("AGENT_DEBUG", "启用调试模式", "调试配置", default=False, input_type="bool"),
    ConfigItem("AGENT_DEBUG_LEVEL", "调试级别", "调试配置", default="basic", options=["basic", "detailed", "trace"]),
    ConfigItem("AGENT_DRY_RUN", "模拟模式（不实际调用 API）", "调试配置", default=False, input_type="bool"),
    ConfigItem("AGENT_LOG_STEPS", "记录处理步骤", "调试配置", default=True, input_type="bool"),
    ConfigItem("AGENT_PERF_TRACK", "性能追踪", "调试配置", default=True, input_type="bool"),
    ConfigItem("AGENT_SAVE_CONTEXT", "保存处理上下文", "调试配置", default=False, input_type="bool"),
    
    # 知识库配置
    ConfigItem("KB_SIMILARITY_THRESHOLD", "知识库相似度阈值", "知识库配置", default=0.7, input_type="float"),
    ConfigItem("KB_REPO", "知识库仓库地址", "知识库配置", default=""),
    ConfigItem("KNOWLEDGE_REPO_URL", "知识库仓库 URL（备选）", "知识库配置", default=""),
    ConfigItem("KB_GITHUB_TOKEN", "知识库专用 GitHub Token", "知识库配置", default="", secret=True),
    
    # 存储配置
    ConfigItem("GITHUB_AGENT_STORAGE__MAX_REPO_SIZE_MB", "最大仓库大小（MB）", "存储配置", default=1000, input_type="int"),
]

# ============ 输入辅助函数 ============

def input_required(prompt: str, default: Optional[str] = None, secret: bool = False) -> str:
    while True:
        display = f" [{default}]" if default and not secret else (" [*****]" if default else "")
        if secret:
            import getpass
            value = getpass.getpass(f"{prompt}{display}: ")
        else:
            value = input(f"{prompt}{display}: ").strip()
        if value:
            return value
        elif default:
            return default
        print_error("此项为必填项")

def input_optional(prompt: str, default: Optional[str] = None) -> Optional[str]:
    display = f" [{default}]" if default else " [直接回车保持当前值]"
    value = input(f"{prompt}{display}: ").strip()
    return value if value else default

def input_confirm(prompt: str, default: bool = False) -> bool:
    default_str = "Y/n" if default else "y/N"
    value = input(f"{prompt} [{default_str}]: ").strip().lower()
    if not value:
        return default
    return value in ('y', 'yes', '是', 'true')

def input_select(prompt: str, options: List[str], default: Optional[str] = None) -> str:
    print(f"\n{prompt}:")
    for i, opt in enumerate(options, 1):
        marker = " (当前)" if opt == default else ""
        print(f"  {i}. {opt}{marker}")
    while True:
        default_str = f" [默认: {options.index(default)+1}]" if default else ""
        value = input(f"请选择 [1-{len(options)}]{default_str}: ").strip()
        if not value and default:
            return default
        try:
            idx = int(value) - 1
            if 0 <= idx < len(options):
                return options[idx]
        except ValueError:
            if value in options:
                return value
        print_error("无效的选择")

def input_int(prompt: str, default: int, min_val: int = 0, max_val: int = 999999) -> int:
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

def input_float(prompt: str, default: float, min_val: float = 0.0, max_val: float = 999999.0) -> float:
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

def prompt_config_item(item: ConfigItem, current_value: Optional[str] = None):
    """提示用户输入单个配置项，显示当前值"""
    # 确定默认值（优先使用当前值，如果没有则使用 item.default）
    if current_value:
        default = current_value
    else:
        default = item.default if item.default is not None else ""
    
    print(f"\n{item.description}")
    
    if item.input_type == "bool":
        # 处理 bool 类型
        bool_default = default if isinstance(default, bool) else (str(default).lower() == 'true')
        value = input_confirm("启用?", default=bool_default)
        return str(value).lower()
    elif item.input_type == "int":
        # 处理 int 类型，确保 default 是有效的整数
        try:
            int_default = int(default) if default else (item.default if isinstance(item.default, int) else 0)
        except (ValueError, TypeError):
            int_default = item.default if isinstance(item.default, int) else 0
        value = input_int("数值", default=int_default)
        return str(value)
    elif item.input_type == "float":
        # 处理 float 类型，确保 default 是有效的浮点数
        try:
            float_default = float(default) if default else (item.default if isinstance(item.default, (int, float)) else 0.0)
        except (ValueError, TypeError):
            float_default = item.default if isinstance(item.default, (int, float)) else 0.0
        value = input_float("数值", default=float_default)
        return str(value)
    elif item.options:
        value = input_select("选择", options=item.options, default=str(default) if default else item.options[0])
        return value
    else:
        if item.secret:
            print(f"{Colors.DIM}当前值: {'*' * 20 if default else '(未设置)'}{Colors.END}")
            return input_optional("新值（直接回车保持当前）", default=default or "") or ""
        else:
            return input_optional("值", default=str(default) if default else "") or ""

# ============ 配置管理 ============

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
    lines.append(f"# 生成时间: {__import__('datetime').datetime.now().isoformat()}")
    lines.append("")
    
    # 按类别组织
    categories = {}
    for item in CONFIG_ITEMS:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)
    
    for category, items in categories.items():
        has_config = any(item.key in config and config[item.key] for item in items)
        if not has_config:
            continue
        
        lines.append(f"# ========== {category} ==========")
        for item in items:
            if item.key in config and config[item.key]:
                lines.append(f"# {item.description}")
                lines.append(f"{item.key}={config[item.key]}")
                lines.append("")
    
    env_file.write_text('\n'.join(lines))
    os.chmod(env_file, 0o600)

# ============ 验证函数 ============

def validate_github_token(token: str) -> tuple:
    if not token:
        return False, "Token 不能为空"
    if not (token.startswith('ghp_') or token.startswith('github_pat_')):
        return False, "Token 格式不正确"
    return True, "格式正确"

def test_github_connection(token: str) -> tuple:
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
            return False, f"HTTP {response.status}"
    except Exception as e:
        return False, str(e)

def generate_webhook_secret() -> str:
    return secrets.token_urlsafe(32)

# ============ 主菜单系统 ============

def show_main_menu(config: Dict[str, str]) -> str:
    """显示主菜单"""
    print_header("GitHub Agent V3 配置管理")
    
    # 显示当前配置摘要
    if config:
        print(f"{Colors.BOLD}当前配置摘要:{Colors.END}")
        has_token = bool(config.get('GITHUB_TOKEN'))
        print(f"  GitHub Token: {Colors.GREEN if has_token else Colors.RED}{'已配置' if has_token else '未配置'}{Colors.END}")
        print(f"  Webhook 端口: {config.get('GITHUB_AGENT_WEBHOOK__PORT', '8000')}")
        print(f"  Ollama 地址: {config.get('GITHUB_AGENT_LLM__OLLAMA_HOST', 'http://localhost:11434')}")
        print(f"  确认模式: {config.get('GITHUB_AGENT_PROCESSING__CONFIRM_MODE', 'manual')}")
        print()
    
    print(f"{Colors.BOLD}操作选项:{Colors.END}")
    print_menu_item("1", "查看完整配置")
    print_menu_item("2", "按类别修改配置")
    print_menu_item("3", "修改单个配置项")
    print_menu_item("4", "重新配置所有（向导模式）")
    print_menu_item("5", "验证配置")
    print_menu_item("0", "保存并退出")
    print()
    
    return input("请选择操作 [0-5]: ").strip()

def show_category_menu(config: Dict[str, str]) -> Optional[str]:
    """显示类别菜单"""
    print_header("选择要修改的配置类别")
    
    # 获取所有类别
    categories = []
    for item in CONFIG_ITEMS:
        if item.category not in categories:
            categories.append(item.category)
    
    for i, cat in enumerate(categories, 1):
        # 统计该类别已配置的项
        items = [it for it in CONFIG_ITEMS if it.category == cat]
        configured = sum(1 for it in items if config.get(it.key))
        status = f"{Colors.GREEN}{configured}/{len(items)}{Colors.END} 已配置"
        print_menu_item(str(i), cat, status)
    
    print_menu_item("0", "返回主菜单")
    print()
    
    choice = input(f"请选择 [0-{len(categories)}]: ").strip()
    if choice == "0":
        return None
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(categories):
            return categories[idx]
    except ValueError:
        pass
    print_error("无效选择")
    return None

def edit_category(config: Dict[str, str], category: str):
    """编辑某个类别的配置"""
    print_header(f"修改配置: {category}")
    
    items = [it for it in CONFIG_ITEMS if it.category == category]
    
    # 显示该类别的所有配置项
    for i, item in enumerate(items, 1):
        current = config.get(item.key, "")
        print(f"\n{i}. {item.description}")
        print_config_item(item.key, current)
        
        if input_confirm("是否修改?", default=False):
            value = prompt_config_item(item, current)
            if value:
                config[item.key] = value
                print_success(f"已更新: {item.key}")
    
    print(f"\n{Colors.GREEN}✅ {category} 配置完成{Colors.END}")

def edit_single_item(config: Dict[str, str]):
    """编辑单个配置项（搜索模式）"""
    print_header("搜索配置项")
    
    keyword = input("输入关键词搜索（如 'port', 'token', 'ollama'）: ").strip().lower()
    if not keyword:
        return
    
    # 搜索匹配的配置项
    matches = [it for it in CONFIG_ITEMS if keyword in it.key.lower() or keyword in it.description.lower()]
    
    if not matches:
        print_warning("未找到匹配的配置项")
        return
    
    print(f"\n找到 {len(matches)} 个匹配项:")
    for i, item in enumerate(matches, 1):
        current = config.get(item.key, "")
        print(f"\n{i}. {item.description} [{item.category}]")
        print_config_item(item.key, current)
    
    choice = input(f"\n请选择要修改的项 [1-{len(matches)}] 或 0 取消: ").strip()
    if choice == "0":
        return
    
    try:
        idx = int(choice) - 1
        if 0 <= idx < len(matches):
            item = matches[idx]
            value = prompt_config_item(item, config.get(item.key))
            if value:
                config[item.key] = value
                print_success(f"已更新: {item.key}")
    except ValueError:
        print_error("无效选择")

def run_full_wizard(config: Dict[str, str]) -> Dict[str, str]:
    """运行完整配置向导"""
    print_header("完整配置向导")
    print_info("此模式将引导你配置所有必要参数\n")
    
    # 按类别分组
    categories = {}
    for item in CONFIG_ITEMS:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)
    
    # 类别顺序
    category_order = [
        "GitHub 认证", "目录配置", "Webhook 配置", "队列配置", "LLM 配置",
        "OpenClaw 配置", "处理配置", "通知配置", "日志配置",
        "知识库配置", "存储配置", "调试配置"
    ]
    
    for category in category_order:
        if category not in categories:
            continue
        items = categories[category]
        
        # 特殊处理可选类别
        if category == "通知配置":
            print_header(f"配置: {category}")
            if not input_confirm("是否配置邮件通知？", default=False):
                continue
        elif category == "OpenClaw 配置":
            print_header(f"配置: {category}")
            if not input_confirm("是否启用 OpenClaw 作为 Fallback？", default=True):
                config["GITHUB_AGENT_LLM__OPENCLAW_ENABLED"] = "false"
                continue
        elif category == "知识库配置":
            print_header(f"配置: {category}")
            if not input_confirm("是否配置知识库？", default=False):
                continue
        else:
            print_header(f"配置: {category}")
        
        for item in items:
            if item.key in ["GITHUB_TOKEN", "GITHUB_WEBHOOK_SECRET"]:
                continue  # 稍后单独处理
            
            current = config.get(item.key)
            value = prompt_config_item(item, current)
            if value is not None:
                config[item.key] = value
    
    # 特殊处理 GitHub Token
    print_header("GitHub Token 验证")
    current_token = config.get("GITHUB_TOKEN", "")
    if current_token:
        print(f"{Colors.DIM}当前 Token: {'*' * 20}{Colors.END}")
        if not input_confirm("是否修改 Token?", default=False):
            pass  # 保持现有
        else:
            config["GITHUB_TOKEN"] = input_github_token()
    else:
        config["GITHUB_TOKEN"] = input_github_token()
    
    # Webhook Secret
    print_header("Webhook Secret")
    current_secret = config.get("GITHUB_WEBHOOK_SECRET", "")
    if current_secret:
        print(f"{Colors.DIM}当前 Secret: {'*' * 20}{Colors.END}")
        if input_confirm("重新生成 Secret?", default=False):
            config["GITHUB_WEBHOOK_SECRET"] = generate_webhook_secret()
            print_success("已生成新的 Webhook Secret")
    else:
        if input_confirm("自动生成 Webhook Secret?", default=True):
            config["GITHUB_WEBHOOK_SECRET"] = generate_webhook_secret()
            print_success("已生成随机 Webhook Secret")
        else:
            config["GITHUB_WEBHOOK_SECRET"] = input_required("Webhook Secret", secret=True)
    
    return config

def input_github_token() -> str:
    """输入并验证 GitHub Token"""
    print_info("获取方式: GitHub → Settings → Developer settings → Personal access tokens")
    print("所需权限: repo, workflow, read:user\n")
    
    while True:
        token = input_required("GitHub Token", secret=True)
        valid, msg = validate_github_token(token)
        if not valid:
            print_error(f"格式错误: {msg}")
            continue
        
        print_info("正在测试连接...")
        success, username = test_github_connection(token)
        if success:
            print_success(f"连接成功！用户: {username}")
            return token
        
        print_error(f"连接失败: {username}")
        if not input_confirm("是否重试?"):
            return token

def show_config(config: Dict[str, str]):
    """显示完整配置"""
    print_header("当前配置详情")
    
    categories = {}
    for item in CONFIG_ITEMS:
        if item.category not in categories:
            categories[item.category] = []
        categories[item.category].append(item)
    
    for category, items in categories.items():
        print(f"\n{Colors.BOLD}{Colors.CYAN}【{category}】{Colors.END}")
        for item in items:
            current = config.get(item.key, "")
            print_config_item(item.key, current, item.description)

def validate_config(config: Dict[str, str]) -> bool:
    """验证配置"""
    print_header("配置验证")
    
    errors = []
    warnings = []
    
    # 必需项检查
    if not config.get('GITHUB_TOKEN'):
        errors.append("缺少 GITHUB_TOKEN")
    if not config.get('GITHUB_WEBHOOK_SECRET'):
        warnings.append("缺少 GITHUB_WEBHOOK_SECRET（安全风险）")
    
    # GitHub 连接测试
    if config.get('GITHUB_TOKEN'):
        print_info("测试 GitHub 连接...")
        success, msg = test_github_connection(config['GITHUB_TOKEN'])
        if success:
            print_success(f"GitHub 连接正常: {msg}")
        else:
            errors.append(f"GitHub 连接失败: {msg}")
    
    # Ollama 测试
    ollama_host = config.get('GITHUB_AGENT_LLM__OLLAMA_HOST', 'http://localhost:11434')
    print_info(f"测试 Ollama ({ollama_host})...")
    try:
        import urllib.request
        req = urllib.request.Request(f"{ollama_host}/api/tags")
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                print_success("Ollama 连接正常")
            else:
                warnings.append(f"Ollama 返回异常: {resp.status}")
    except Exception as e:
        warnings.append(f"Ollama 连接失败: {e}")
    
    print()
    if errors:
        print_error(f"发现 {len(errors)} 个错误:")
        for e in errors:
            print(f"  ❌ {e}")
    if warnings:
        print_warning(f"发现 {len(warnings)} 个警告:")
        for w in warnings:
            print(f"  ⚠️  {w}")
    if not errors and not warnings:
        print_success("配置验证通过！")
        return True
    return len(errors) == 0

def run_wizard():
    """主入口"""
    # 加载现有配置
    existing = load_existing_config()
    config = existing.copy()
    
    if not existing:
        print_info("未检测到现有配置，进入完整配置向导\n")
        config = run_full_wizard(config)
        save_config(config)
        print_success("配置完成！")
        return
    
    # 进入交互式菜单
    while True:
        choice = show_main_menu(config)
        
        if choice == "0":
            # 保存并退出
            if config != existing:
                save_config(config)
                print_success("配置已保存")
            else:
                print_info("配置未更改")
            break
        
        elif choice == "1":
            show_config(config)
        
        elif choice == "2":
            category = show_category_menu(config)
            if category:
                edit_category(config, category)
        
        elif choice == "3":
            edit_single_item(config)
        
        elif choice == "4":
            if input_confirm("确定要重新配置所有项? 当前配置将被覆盖", default=False):
                config = run_full_wizard(config)
        
        elif choice == "5":
            validate_config(config)
        
        else:
            print_error("无效选择")

if __name__ == '__main__':
    run_wizard()
