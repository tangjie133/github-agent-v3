#!/bin/bash
# GitHub Agent V3 启动脚本

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

echo -e "${GREEN}Starting GitHub Agent V3...${NC}"

# 检查 Python
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}Error: python3 not found${NC}"
    exit 1
fi

# 检查虚拟环境
if [ -d "venv" ]; then
    echo -e "${YELLOW}Activating virtual environment...${NC}"
    source venv/bin/activate
fi

# 检查必要的环境变量
if [ -z "$GITHUB_TOKEN" ] && [ -z "$GITHUB_APP_ID" ]; then
    echo -e "${YELLOW}Warning: GITHUB_TOKEN or GITHUB_APP_ID not set${NC}"
    echo "Set one of them before starting:"
    echo "  export GITHUB_TOKEN=ghp_xxx"
    echo "  or"
    echo "  export GITHUB_APP_ID=xxx"
    echo "  export GITHUB_APP_PRIVATE_KEY='-----BEGIN...'"
fi

if [ -z "$GITHUB_WEBHOOK_SECRET" ]; then
    echo -e "${YELLOW}Warning: GITHUB_WEBHOOK_SECRET not set (production only)${NC}"
fi

# 运行诊断
echo -e "${YELLOW}Running diagnostics...${NC}"
python diagnose.py || true

echo ""
echo -e "${GREEN}Starting server...${NC}"
echo "Webhook endpoint: http://localhost:8000/webhook"
echo "Health check:   http://localhost:8000/health"
echo ""

# 启动服务
exec python main.py