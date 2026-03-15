# 知识库使用指南

本文档介绍如何向知识库添加数据手册和最佳实践。

## 📁 目录结构

```
knowledge_base/
├── chips/              # 芯片数据手册 (.md 格式)
├── best_practices/     # 最佳实践文档 (.md 格式)
├── data/              # 向量数据库文件
├── pdf_to_kb.py       # PDF 转换工具
├── auto_kb_loader.py  # 本地文件夹自动加载工具
├── github_repo_watcher.py  # GitHub 仓库同步工具
└── github_webhook_server.py # GitHub Webhook 接收器
```

## 🚀 快速添加数据手册

### 方式 1: GitHub 仓库自动同步（推荐！）

将数据手册存入 GitHub 仓库，自动同步到知识库。

**步骤 1: 配置 Webhook（实时同步）**

```bash
# 1. 启动 Webhook 接收服务器
python scripts/github_webhook_server.py --port 9000

# 2. 在 GitHub 仓库设置 Webhook
#    - URL: http://your-server:9000/webhook
#    - Secret: 与 GITHUB_WEBHOOK_SECRET 环境变量一致
#    - 事件: Just the push event
```

**步骤 2: 或定时同步（备用方案）**

```bash
# 手动同步一次
python scripts/github_repo_watcher.py --sync

# 后台监控（每 5 分钟检查一次）
python scripts/github_repo_watcher.py --daemon --interval 300
```

**支持的文件格式：**
- `.md` - 直接使用
- `.txt` - 转换为 Markdown
- `.pdf` - 提取文本后转换
- `.docx` - 转换为 Markdown

### 方式 2: 本地文件转换

```bash
# 转换单个 PDF
python scripts/pdf_to_kb.py /path/to/SD3031.pdf

# 批量转换整个文件夹
python scripts/pdf_to_kb.py /path/to/pdf/folder/ --batch
```

### 方式 3: 本地文件夹监控

```bash
# 监控文件夹，自动处理新添加的 PDF
python scripts/auto_kb_loader.py --watch /path/to/pdf/folder
```

## 📋 查看知识库状态

```bash
# 列出所有文档
python scripts/auto_kb_loader.py --list

# 输出示例:
# 📚 当前知识库文档 (3 个):
# ==================================================
#  1. SD3031.md                        (1925 bytes)
#  2. DS3231.md                        (2341 bytes)
#  3. STM32F103.md                     (4521 bytes)
# ==================================================
```

## 📝 手动添加 Markdown

如果 PDF 转换效果不佳，可以直接创建 Markdown 文件：

```bash
# 放入 chips 目录
cp /path/to/your/manual.md knowledge_base/chips/CHIP_NAME.md

# 或放入 best_practices 目录
cp /path/to/guide.md knowledge_base/best_practices/python_guide.md
```

## ⚙️ 环境变量配置（推荐方式）

编辑 `.env` 文件配置 GitHub 知识库同步：

```bash
# ============================================
# GitHub 知识库同步配置
# ============================================
# 启用 GitHub 仓库同步
KB_GITHUB_SYNC_ENABLED=true

# GitHub 仓库地址 (格式: owner/repo)
KB_REPO=tangjie133/knowledge-base

# 分支名称
KB_BRANCH=main

# GitHub Token (用于私有仓库，可选)
# KB_GITHUB_TOKEN=ghp_xxxxxxxxxxxxxxxx

# 自动同步间隔（秒），0 表示不同步，仅使用 Webhook
KB_SYNC_INTERVAL=300

# 启用 Webhook 实时同步
KB_WEBHOOK_ENABLED=true
KB_WEBHOOK_PORT=9000
KB_WEBHOOK_SECRET=your_webhook_secret
```

配置完成后，只需运行：
```bash
./scripts/start.sh --port 8080
```

启动脚本会自动：
1. 启动 KB Service
2. 执行初始同步
3. 启动定时同步（如果配置了间隔）
4. 启动 Webhook 服务器（如果启用）
5. 启动主服务

### 快速配置向导

```bash
# 运行配置向导
./scripts/setup_github_kb.sh

# 或手动编辑 .env 文件
nano .env
```

## 🔄 生效方式

添加文档后，**重启服务**即可自动加载：

```bash
# 重启服务
./scripts/start.sh --port 8080

# 查看日志确认加载
# INFO:__main__:✅ KB Service is ready
# INFO:__main__:   Documents: 3
```

## 📊 支持的格式

| 格式 | 位置 | 说明 |
|------|------|------|
| `.md` | `chips/` | 芯片数据手册 |
| `.md` | `best_practices/` | 开发最佳实践 |
| `.pdf` | 任意 | 需转换为 .md |

## 💡 最佳实践

### 1. 文件命名规范
- 使用芯片型号命名，如 `SD3031.md`, `DS3231.md`
- 避免中文文件名
- 使用大写字母和数字

### 2. 文档内容建议
芯片手册应包含：
- 芯片简介和主要特性
- 引脚定义和封装信息
- 寄存器列表和说明
- 通信协议（I2C/SPI 地址、时序）
- 常见问题及解决方法
- 参考代码示例

### 3. 批量维护
建立固定的 PDF 文件夹，使用监控模式：

```bash
# 创建专用文件夹
mkdir -p ~/chip_manuals

# 启动监控
python scripts/auto_kb_loader.py --watch ~/chip_manuals

# 以后只需将 PDF 复制到该文件夹，自动转换
```

## 🔧 故障排查

### PDF 转换失败
```bash
# 检查 pdftotext 是否安装
which pdftotext

# 如未安装
sudo apt-get install poppler-utils
```

### 文档未加载
1. 检查文件是否在正确目录
2. 检查文件扩展名是否为 `.md`
3. 重启服务

### 向量搜索无结果
- 检查文档内容是否足够（至少 100 字符）
- 检查 Ollama 是否运行 (`curl http://localhost:11434/api/tags`)
- 检查 nomic-embed-text 模型是否可用
