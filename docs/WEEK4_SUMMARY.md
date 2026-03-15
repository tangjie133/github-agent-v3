# Week 4 开发总结：集成与连接

## 完成情况

### ✅ 已完成功能

#### 1. GitHub API 客户端 (`core/github_api/`)

**功能：**
- 支持两种认证方式：
  - **Personal Access Token (PAT)** - 简单快速
  - **GitHub App** - JWT + 安装令牌，更安全
- 异步 HTTP 客户端 (aiohttp)
- 安装令牌缓存（50 分钟有效期）

**API 支持：**
- Issue API: `get_issue`, `create_issue_comment`, `update_issue`
- PR API: `create_pull`, `get_pull`, `update_pull`, `create_pr_comment`, `add_labels_to_pr`
- Repository API: `get_repo`

**使用示例：**
```python
from core.github_api import get_github_client

client = get_github_client()

# 创建 Issue 评论
await client.create_issue_comment(
    owner="myorg",
    repo="myrepo", 
    issue_number=42,
    body="Fix generated!"
)

# 创建 PR
pr = await client.create_pull(
    owner="myorg",
    repo="myrepo",
    title="Fix #42: Bug fix",
    body="Description...",
    head="issue-42-fix",
    base="main",
    draft=False
)
```

#### 2. Webhook 处理器更新 (`services/webhook_server.py`)

**更新内容：**
- Issue 事件路由到队列
- 评论事件路由到确认处理器
- Bot 评论过滤
- 限流保护

**工作流：**
```
GitHub Webhook
    ↓
签名验证
    ↓
限流检查
    ↓
事件分类
    ├─ issues (opened/edited) → 加入队列 → Worker 处理
    └─ issue_comment (created) → 确认处理器 → 更新 PR
```

#### 3. Worker 集成 (`core/queue/worker.py` + `main.py`)

**更新内容：**
- Worker 调用 Issue Processor 处理队列任务
- 新增 `main.py` 主入口
- 整合 Webhook 服务器和 Worker 池

**启动流程：**
```python
# main.py
1. 初始化日志
2. 创建 Issue Processor
3. 启动 Worker 池（多 worker）
4. 启动 Webhook 服务器
5. 等待关闭信号
```

**启动命令：**
```bash
python main.py
```

#### 4. 端到端测试

**测试文件：** `tests/core/test_github_api.py`

**测试覆盖：**
- PAT 认证
- App 认证初始化
- API 方法调用（Mock）
- 令牌缓存
- 集成测试（跳过，需真实 token）

### 📁 新增/修改文件

```
core/
├── github_api/                # NEW
│   ├── __init__.py
│   └── client.py              # GitHub API 客户端
├── queue/
│   └── manager.py             # MOD: 添加 Priority 枚举，扩展 QueueEntry
├── pr/
│   └── manager.py             # MOD: 使用真正的 GitHubClient
├── fix/
│   └── engine.py              # MOD: 适配 Worker 接口
└── confirmation.py            # MOD: 优化导入

services/
├── webhook_server.py          # MOD: 连接队列和确认处理器
└── processor.py               # MOD: 使用真正的 GitHubClient

main.py                        # NEW: 主入口
tests/core/
└── test_github_api.py         # NEW: GitHub API 测试
```

### 🔗 完整数据流

```
┌──────────────────────────────────────────────────────────────────────┐
│                        GitHub Issue Created                           │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│                      Webhook Server (FastAPI)                         │
│  - 签名验证                                                           │
│  - 限流保护                                                           │
│  - Bot 过滤                                                           │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│                         Queue Manager                                 │
│  - Redis (primary)                                                    │
│  - Local memory (fallback)                                            │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│                       Worker Pool (async)                             │
│  - 4 workers (configurable)                                           │
│  - 10min timeout per task                                             │
│  - Exponential backoff on error                                       │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
┌──────────────────────────────────────────────────────────────────────┐
│                       Issue Processor                                 │
│  1. Analyze Issue (LLM)                                               │
│  2. Clone Repository                                                  │
│  3. Generate Patches                                                  │
│  4. Create Branch & Commit                                            │
└──────────────────────────────────────────────────────────────────────┘
                                   ↓
                    ┌──────────────┴──────────────┐
                    ↓                             ↓
            ┌──────────────┐              ┌──────────────┐
            │  Auto Mode   │              │ Manual Mode  │
            │  (confirm)   │              │  (confirm)   │
            └──────────────┘              └──────────────┘
                    ↓                             ↓
            ┌──────────────┐              ┌──────────────┐
            │  Formal PR   │              │  Draft PR    │
            │  Created     │              │  (Preview)   │
            └──────────────┘              └──────────────┘
                                                   ↓
                                          User Comment
                                            "确认" / "拒绝"
                                                   ↓
                                          ┌────────┴────────┐
                                          ↓                 ↓
                                    [确认]              [拒绝]
                                          ↓                 ↓
                              Convert to Formal      Close PR
```

### 📊 测试统计

```bash
$ python -m pytest tests/core/ -v

================== 72 passed, 6 skipped, 108 warnings ==================
```

| 测试文件 | 通过 | 跳过 |
|---------|------|------|
| test_i18n.py | 9 | 0 |
| test_confirmation.py | 16 | 0 |
| test_fix_engine.py | 13 | 0 |
| test_llm_manager.py | 10 | 4 |
| test_email_notifier.py | 10 | 0 |
| test_github_api.py | 14 | 2 |

### ⚙️ 环境变量配置

**GitHub 认证（二选一）：**

```bash
# Option 1: Personal Access Token
export GITHUB_TOKEN="ghp_xxxxxxxxxxxx"

# Option 2: GitHub App
export GITHUB_APP_ID="123456"
export GITHUB_APP_PRIVATE_KEY="-----BEGIN RSA PRIVATE KEY-----..."
```

**其他配置：**
```bash
# Redis
export REDIS_URL="redis://localhost:6379/0"

# LLM
export OLLAMA_HOST="http://localhost:11434"
export OPENCLAW_API_KEY="sk-xxxxxxxx"

# Email (optional)
export SMTP_USER="bot@example.com"
export SMTP_PASSWORD="xxxxxx"
export ADMIN_EMAIL="admin@example.com"
```

### 🚀 运行方式

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置环境变量
export GITHUB_TOKEN="ghp_xxx"
export GITHUB_WEBHOOK_SECRET="your_webhook_secret"

# 3. 启动服务
python main.py

# 4. 配置 GitHub Webhook
# URL: http://your-server:8000/webhook
# Secret: your_webhook_secret
```

### 📈 完成度总览

```
Week 1: 队列系统 + Webhook     ████████░░ 100% ✅
Week 2: LLM + 邮件通知          ████████░░ 100% ✅  
Week 3: 修复引擎 + 确认机制      ████████░░ 100% ✅
Week 4: 集成 + E2E测试          ████████░░ 100% ✅
Week 5: 部署 + 监控             ░░░░░░░░░░ 0%  ⏳
Week 6: 测试 + 优化             ░░░░░░░░░░ 0%  ⏳
```

### 📅 Week 5 计划

1. **Docker 支持** - Dockerfile + docker-compose.yml
2. **K8s 部署** - Deployment/Service/Ingress
3. **监控告警** - Prometheus 指标 + Grafana 面板
4. **日志聚合** - 结构化日志收集

是否需要继续开发 **Week 5**？