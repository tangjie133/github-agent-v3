# Python 虚拟环境使用指南

本文档说明如何在 GitHub Agent V3 项目中使用 Python 虚拟环境，防止环境污染。

## 为什么需要虚拟环境？

| 问题 | 虚拟环境解决方案 |
|------|----------------|
| 不同项目依赖版本冲突 | 每个项目独立的包空间 |
| 系统 Python 被污染 | 项目依赖不写入系统 Python |
| 部署困难 | 依赖清单明确，易于复现 |
| 卸载残留 | 直接删除 venv 文件夹即可 |

## 快速开始

### 1. 自动设置（推荐）

```bash
./setup.sh
```

脚本会自动：
- 检查 Python 版本（>= 3.10）
- 创建虚拟环境
- 安装依赖

### 2. 手动设置

```bash
# 创建虚拟环境
make venv

# 激活环境
source venv/bin/activate

# 安装依赖
make install

# 退出环境
deactivate
```

## 日常使用流程

```bash
# 进入项目目录
cd github-agent-v3

# 激活虚拟环境（每次新终端都需要）
source venv/bin/activate

# 运行命令
make dev
make test

# 退出虚拟环境
deactivate
```

## 常用命令速查

| 命令 | 说明 |
|------|------|
| `make venv` | 创建虚拟环境（仅首次） |
| `make setup` | 完整设置（venv + 依赖） |
| `source venv/bin/activate` | 激活环境 |
| `deactivate` | 退出环境 |
| `make clean` | 清理临时文件 |
| `make clean-all` | 清理所有（含 venv） |
| `make freeze` | 锁定依赖版本 |

## 多版本 Python

如果你的系统有多个 Python 版本：

```bash
# 指定 Python 版本创建虚拟环境
python3.12 -m venv venv

# 或使用 virtualenv
virtualenv -p python3.12 venv
```

## VS Code 集成

项目已配置 `.vscode/settings.json`，VS Code 会自动：
- 识别虚拟环境中的 Python 解释器
- 激活终端环境

如果没有自动识别：
1. 按 `Ctrl+Shift+P`（或 `Cmd+Shift+P`）
2. 输入 "Python: Select Interpreter"
3. 选择 `./venv/bin/python`

## 故障排查

### 1. 激活环境后仍使用系统 Python

```bash
# 检查当前 Python 路径
which python
# 应输出: /path/to/project/venv/bin/python

# 如果不是，重新激活
source venv/bin/activate
```

### 2. pip 安装包后找不到

```bash
# 确认在虚拟环境中
which pip
# 应输出: /path/to/project/venv/bin/pip

# 重新激活环境
source venv/bin/activate
```

### 3. 删除虚拟环境重新创建

```bash
# 完全清理
make clean-all

# 重新创建
make setup
```

### 4. 权限问题

```bash
# 如果 venv 创建失败，检查权限
# 或者使用用户目录
python3 -m venv ~/.venvs/github-agent
source ~/.venvs/github-agent/bin/activate
```

## 与其他工具对比

| 工具 | 适用场景 | 复杂度 |
|------|---------|--------|
| **venv** | 本项目使用，Python 内置 | ⭐ 简单 |
| virtualenv | 需要更多功能 | ⭐⭐ 中等 |
| conda | 数据科学，管理非 Python 依赖 | ⭐⭐⭐ 复杂 |
| Poetry | 现代 Python 项目管理 | ⭐⭐ 中等 |
| pipenv | Pipfile 管理依赖 | ⭐⭐ 中等 |

本项目使用 **venv**，因为它是 Python 标准库的一部分，无需额外安装。

## 最佳实践

1. **始终使用虚拟环境**：即使是小项目
2. **提交 requirements.txt**：但不提交 venv 文件夹
3. **定期更新依赖**：`pip list --outdated`
4. **锁定生产版本**：`make freeze` 生成 requirements.lock.txt
5. **.gitignore 排除 venv**：已配置，不会误提交
