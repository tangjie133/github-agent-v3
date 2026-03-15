#!/bin/bash
cd /home/tj/.npm-global/lib/node_modules/openclaw/skills/github-agent-v3
source venv/bin/activate

# 清理旧进程
pkill -f "python -m services.webhook_server" 2>/dev/null
pkill -f "python main.py" 2>/dev/null
sleep 2

# 启动服务
python -m services.webhook_server &
echo $! > /tmp/webhook.pid

python main.py &
echo $! > /tmp/main.pid

echo "Services started"
sleep 2
curl -s http://localhost:8080/health
