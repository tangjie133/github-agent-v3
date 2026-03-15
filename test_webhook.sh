#!/bin/bash
# Webhook 测试脚本

# 读取 .env 获取 webhook secret
if [ -f .env ]; then
    export $(cat .env | grep -v '^#' | xargs)
fi

WEBHOOK_SECRET="${GITHUB_WEBHOOK_SECRET:-test-secret}"
PAYLOAD='{"action":"opened","repository":{"full_name":"test-org/test-repo"},"issue":{"number":1,"title":"Fix print statement","body":"Use logging instead of print"}}'

# 计算签名
SIGNATURE=$(echo -n "$PAYLOAD" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" | sed 's/^.* //')

echo "Testing webhook with signature..."
echo "Secret: $WEBHOOK_SECRET"
echo "Signature: sha256=$SIGNATURE"
echo ""

curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-Hub-Signature-256: sha256=$SIGNATURE" \
  -d "$PAYLOAD"

echo ""
