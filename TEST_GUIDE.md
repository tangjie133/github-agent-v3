# GitHub Agent V3 功能验证指南

## 第一步：基础健康检查

### 1.1 服务启动检查
```bash
# 1. 启动服务（保持前台运行）
make dev

# 2. 另开终端测试健康检查
curl http://localhost:8000/health

# 预期输出:
{"status":"ok","version":"3.0.0","timestamp":"..."}
```

### 1.2 诊断工具
```bash
# 运行完整诊断
make diagnose

# 或使用 Python 直接运行
python diagnose.py
```

预期通过项：
- ✅ GitHub 认证
- ✅ Ollama 连接
- ✅ 存储目录可写
- ✅ 队列系统正常

---

## 第二步：Webhook 测试

### 2.1 本地模拟 Webhook
```bash
# 使用 curl 模拟 Issue 创建事件
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -H "X-GitHub-Event: issues" \
  -H "X-Hub-Signature-256: sha256=..." \
  -d '{
    "action": "opened",
    "repository": {
      "full_name": "test-org/test-repo"
    },
    "issue": {
      "number": 1,
      "title": "测试 Issue: 修复打印语句",
      "body": "需要把 print 改成 logging"
    }
  }'
```

### 2.2 查看日志输出
启动服务的终端会显示：
- Webhook 接收日志
- Issue 分析日志
- 队列任务创建日志

---

## 第三步：LLM 连接测试

### 3.1 Ollama 测试
```bash
# 1. 确认 Ollama 服务运行
curl http://localhost:11434/api/tags

# 2. 测试模型可用性
curl http://localhost:11434/api/generate -d '{
  "model": "qwen3-coder:30b",
  "prompt": "Hello"
}'
```

### 3.2 代码分析测试
创建测试脚本：
```bash
python << 'EOF'
import asyncio
from services.processor import get_issue_processor

async def test():
    processor = get_issue_processor()
    result = await processor.analyze_code(
        repo_path=".",
        issue_title="Fix print statement",
        issue_body="Change print to logging"
    )
    print(f"分析结果: {result}")

asyncio.run(test())
EOF
```

---

## 第四步：完整流程测试（真实 GitHub）

### 4.1 创建测试仓库
1. 在 GitHub 创建测试仓库（如 `test-agent-repo`）
2. 添加简单 Python 文件：
```python
# test.py
print("Hello World")  # TODO: use logging
```

### 4.2 配置 Webhook
1. 仓库 Settings → Webhooks → Add webhook
2. Payload URL: `http://你的服务器IP:8000/webhook`
3. Content type: `application/json`
4. Secret: 你的 `GITHUB_WEBHOOK_SECRET`
5. 选择 Events: **Issues** 和 **Issue comments**

### 4.3 创建测试 Issue
在 GitHub 创建 Issue：
- 标题: `Fix: Replace print with logging`
- 内容: `Use proper logging instead of print statements`

### 4.4 观察处理流程
服务日志应显示：
```
1. Webhook 接收
2. Issue 分析启动
3. LLM 代码分析
4. 修复方案生成
5. PR 创建（或等待确认）
```

---

## 第五步：确认机制测试

### 5.1 人工确认模式
1. 配置 `CONFIRM_MODE=manual`
2. 创建 Issue 触发修复
3. 查看 GitHub 评论中的确认请求
4. 回复 `@github-agent confirm` 确认修复

### 5.2 自动确认模式
1. 配置 `CONFIRM_MODE=auto`
2. 设置 `AUTO_CONFIRM_THRESHOLD=0.8`
3. 创建 Issue
4. 观察自动 PR 创建

---

## 第六步：知识库测试（可选）

### 6.1 知识库同步
```bash
# 同步知识库
python -c "from knowledge_base.knowledge_sync import sync_knowledge_base; sync_knowledge_base()"
```

### 6.2 相似 Issue 匹配
创建与历史 Issue 相似的 Issue，观察是否能匹配到历史修复方案。

---

## 第七步：故障注入测试

### 7.1 测试错误处理
```bash
# 1. 测试无效 Token
curl -X POST http://localhost:8000/webhook \
  -H "Content-Type: application/json" \
  -d '{"action": "opened", "repository": {"full_name": "invalid/repo"}}'

# 2. 观察错误日志和邮件通知（如果配置了）
```

### 7.2 测试队列满载
创建大量 Issue，观察队列处理情况：
```bash
for i in {1..10}; do
  curl -X POST http://localhost:8000/webhook ... &
done
```

---

## 第八步：性能测试

### 8.1 并发处理测试
```bash
# 使用 ab 或 wrk 进行压力测试
ab -n 100 -c 10 -p payload.json -T application/json http://localhost:8000/webhook
```

### 8.2 观察指标
- 响应时间
- 队列堆积情况
- Worker 负载

---

## 验证清单

| 功能 | 测试方法 | 预期结果 |
|------|---------|---------|
| 服务启动 | `make dev` | 正常启动，端口 8000 |
| 健康检查 | `curl /health` | 返回 status: ok |
| GitHub API | `make diagnose` | 连接成功 |
| Ollama | `curl /api/tags` | 返回模型列表 |
| Webhook 接收 | curl 模拟 | 返回 200 |
| Issue 分析 | 创建测试 Issue | 日志显示分析过程 |
| 代码修复 | 触发修复 | 生成正确补丁 |
| PR 创建 | 确认修复 | GitHub 出现 PR |
| 邮件通知 | 配置 SMTP | 收到通知邮件 |
| 队列处理 | 并发请求 | 正常排队处理 |

---

## 常见问题

### Q: Webhook 测试返回 403?
检查 `GITHUB_WEBHOOK_SECRET` 是否正确配置。

### Q: Ollama 连接失败?
```bash
# 检查 Ollama 状态
curl http://localhost:11434/api/tags

# 检查模型是否存在
ollama list
```

### Q: PR 没有创建?
1. 检查 GitHub Token 权限（需要 `repo`）
2. 查看日志中的错误信息
3. 确认是否为 Fork 仓库（需要额外权限）

### Q: 队列任务卡住?
```bash
# 检查 Worker 状态
curl http://localhost:8000/metrics

# 重启服务
Ctrl+C
make dev
```

---

## 下一步

基础验证通过后，可以：
1. 配置生产环境（Redis、监控）
2. 调整模型参数优化修复质量
3. 建立知识库积累历史修复
4. 配置告警和监控
