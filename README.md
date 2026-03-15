# GitHub Agent V3

智能 GitHub Issue 自动修复系统，支持代码分析、多文件修复和人工确认。

## 核心特性

- 🤖 **智能修复**：自动分析 Issue，生成代码修复方案
- 🔄 **多级 Fallback**：Ollama → OpenClaw → 模板生成器
- ✅ **人工确认**：支持自动/手动确认模式，安全可控
- 🌐 **双语支持**：中英文自动检测和响应
- 📦 **多文件修复**：支持跨文件依赖的复杂修复
- 🚀 **异步处理**：基于队列的异步架构，支持高并发

## 快速开始（5分钟）

### 方式一：使用虚拟环境（推荐）

```bash
# 1. 克隆项目
git clone <repository>
cd github-agent-v3

# 2. 一键设置虚拟环境（Python 3.10+）
./setup.sh
# 或手动: make setup

# 3. 激活虚拟环境
source venv/bin/activate

# 4. 交互式配置（推荐）
make config
# 或手动: cp .env.example .env && 编辑 .env

# 5. 启动服务
make start            # 生产模式
# 或 make dev         # 调试模式（详细日志）
```

### 方式二：全局安装（不推荐）

```bash
make install          # 直接安装到系统 Python（可能污染环境）
```

**为什么使用虚拟环境？**
- ✅ 隔离项目依赖，避免与系统 Python 冲突
- ✅ 每个项目可以有不同的依赖版本
- ✅ 便于部署和迁移
- ✅ 删除项目时不会残留无用包

服务启动后：
- Webhook 地址：`http://localhost:8000/webhook`
- 健康检查：`http://localhost:8000/health`

### 配置 GitHub Webhook

1. 进入 GitHub 仓库 → Settings → Webhooks → Add webhook
2. 填写：
   - **Payload URL**: `http://your-server:8000/webhook`
   - **Content type**: `application/json`
   - **Secret**: 你的 `GITHUB_WEBHOOK_SECRET`
   - **Events**: Issues, Issue comments
3. 保存

## 常用命令

### 虚拟环境管理
```bash
make venv         # 创建虚拟环境
make setup        # 完整环境设置（venv + 依赖）
source venv/bin/activate   # 激活环境
deactivate        # 退出环境
make clean-all    # 清理虚拟环境
```

### 配置管理
```bash
make config           # 交互式配置向导
make config-show      # 显示当前配置（脱敏）
make config-validate  # 验证配置完整性
```

### 开发命令
```bash
make help         # 查看所有命令
make start        # 启动服务（生产模式）
make dev          # 调试模式（详细日志）
make test         # 运行测试
make diagnose     # 诊断检查
make lint         # 代码检查
make format       # 代码格式化
make freeze       # 导出锁定依赖
```

## 配置管理

本项目提供两种配置方式：

### 方式一：交互式配置向导（推荐）

```bash
make config
```

向导会引导你完成：
1. **GitHub 配置** - Token 验证、Webhook Secret 生成
2. **LLM 配置** - Ollama/OpenClaw 设置
3. **高级配置** - 确认模式、通知邮箱等

特点：
- ✅ 自动验证 GitHub Token 有效性
- ✅ 自动生成安全的 Webhook Secret
- ✅ 测试 Ollama 连接
- ✅ 配置保存为 `.env` 文件（权限 600）

### 方式二：手动配置

```bash
cp .env.example .env
# 编辑 .env 文件
```

### 查看和验证配置

```bash
make config-show      # 显示当前配置（敏感信息已脱敏）
make config-validate  # 验证配置并测试连接
```

## 配置说明

### 必需配置

| 变量 | 说明 | 获取方式 |
|------|------|---------|
| `GITHUB_TOKEN` | GitHub Personal Access Token | GitHub Settings → Developer settings → Personal access tokens |
| `GITHUB_WEBHOOK_SECRET` | Webhook 签名密钥 | 随机字符串，与 GitHub Webhook 配置一致 |

### 可选配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama 服务地址 |
| `REDIS_URL` | 内存队列 | Redis 连接 URL（可选） |
| `CONFIRM_MODE` | `manual` | 修复确认模式: manual/auto |
| `ADMIN_EMAIL` | - | 管理员邮箱（失败通知） |

完整配置示例见 `.env.example`

## Docker 部署（可选）

```bash
# Docker Compose
docker-compose -f docker-compose.simple.yml up -d

# 纯 Docker
docker build -t github-agent:v3 .
docker run -d -p 8000:8000 --env-file .env github-agent:v3
```

## 故障排查

### Ollama 连接失败
```bash
curl http://localhost:11434/api/tags
export OLLAMA_HOST=http://ollama-server:11434
```

### GitHub API 认证失败
```bash
export GITHUB_TOKEN=your_token
curl -H "Authorization: Bearer $GITHUB_TOKEN" https://api.github.com/user
```

### Webhook 接收不到事件
1. 检查防火墙 8000 端口
2. 内网需用 ngrok 暴露服务
3. 检查 `GITHUB_WEBHOOK_SECRET` 是否匹配

**有问题？** 运行 `make diagnose` 获取诊断报告。

## 目录结构

```
github-agent-v3/
├── core/               # 核心模块
│   ├── config.py       # 配置管理
│   ├── logging.py      # 结构化日志
│   ├── queue/          # 队列系统
│   ├── llm/            # LLM 管理
│   ├── fix/            # 代码修复引擎
│   ├── git/            # Git 操作
│   ├── pr/             # PR 管理
│   └── github_api/     # GitHub API 客户端
├── services/           # 服务层
│   ├── processor.py    # Issue 处理器
│   └── webhook_server.py
├── tests/              # 测试
├── main.py             # 入口
├── Makefile            # 命令集合
└── .env.example        # 配置示例
```

## 技术栈

- **Python 3.12** + **FastAPI** - 异步 Web 框架
- **Ollama** - 本地 LLM (qwen3-coder:30b)
- **Redis** - 队列（可选，默认内存队列）
- **Git** - 仓库操作

## 开发状态

- ✅ 核心功能完成（Week 1-4）
- ✅ 代码质量优化（0 warnings, 72 tests passed）
- ✅ 个人/团队使用就绪
- ⏳ 生产级部署（后续按需添加）

## 许可证

MIT