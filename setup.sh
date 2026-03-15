#!/bin/bash
# GitHub Agent V3 - 一键环境设置脚本

set -e  # 遇到错误立即退出

echo "🚀 GitHub Agent V3 环境设置"
echo ""

# 检查 Python 版本
echo "🔍 检查 Python 版本..."
PYTHON_VERSION=$(python3 --version 2>&1 | awk '{print $2}')
REQUIRED_VERSION="3.10"

if [ "$(printf '%s\n' "$REQUIRED_VERSION" "$PYTHON_VERSION" | sort -V | head -n1)" != "$REQUIRED_VERSION" ]; then
    echo "❌ 错误: Python 版本过低 ($PYTHON_VERSION)，需要 >= $REQUIRED_VERSION"
    exit 1
fi
echo "✅ Python 版本: $PYTHON_VERSION"

# 检查 make
echo "🔍 检查 make..."
if ! command -v make &> /dev/null; then
    echo "❌ 错误: 未安装 make"
    echo "   Ubuntu/Debian: sudo apt install make"
    echo "   MacOS: xcode-select --install"
    exit 1
fi
echo "✅ make 已安装"

# 创建虚拟环境并安装依赖
echo ""
echo "🔧 正在设置虚拟环境..."
make setup

echo ""
echo "🎉 环境设置完成！"
echo ""
echo "📋 下一步:"
echo "   1. 运行配置向导: make config"
echo "      （交互式配置，推荐）"
echo "   2. 或手动配置: cp .env.example .env && 编辑 .env"
echo "   3. 启动服务: make dev"
echo ""
echo "💡 提示: 运行 'make help' 查看所有可用命令"
