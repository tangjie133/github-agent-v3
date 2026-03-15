# GitHub 真实环境测试指南

## 第一步：确保服务可访问

### 方案 A：公网服务器
如果你部署在公网服务器，直接使用服务器 IP 或域名。

### 方案 B：内网穿透（推荐用于本地测试）
```bash
# 使用 ngrok 暴露本地服务
ngrok http 8000

# 会获得一个公网 URL，如：https://abc123.ngrok.io
# Webhook URL: https://abc123.ngrok.io/webhook
```

---

## 第二步：GitHub 仓库配置

### 1. 创建测试仓库
在 GitHub 创建一个新仓库，例如：`test-github-agent`

### 2. 添加测试文件
创建一个包含问题的 Python 文件：
```python
# hello.py
print("Hello World")  # TODO: use logging instead of print

def add(a, b):
    return a + b
```

### 3. 配置 Webhook
进入仓库 **Settings → Webhooks → Add webhook**：

| 配置项 | 值 |
|--------|-----|
| **Payload URL** | `https://你的服务器/webhook` 或 `https://abc123.ngrok.io/webhook` |
| **Content type** | `application/json` |
| **Secret** | 你的 `GITHUB_WEBHOOK_SECRET` |
| **SSL verification** | Enable (生产) / Disable (测试用自签名证书) |

### 4. 选择事件
勾选以下事件：
- ✅ **Issues**
- ✅ **Issue comments**

点击 **Add webhook**

---

## 第三步：创建测试 Issue

### 测试场景 1：简单的 print 修复
**标题：** `Fix: Replace print with logging`

**内容：**
```markdown
The code uses print statements which is not suitable for production.

Please replace with proper logging.

File: hello.py
```

**预期结果：**
1. Agent 接收到 webhook
2. 分析 Issue 和代码
3. 生成修复方案
4. 创建 PR（自动模式）或评论请求确认（人工模式）

---

### 测试场景 2：函数文档
**标题：** `Add docstring to add function`

**内容：**
```markdown
The `add` function lacks documentation. Please add proper docstring.
```

---

### 测试场景 3：错误处理
**标题：** `Fix: Add error handling`

**内容：**
```markdown
The add function should handle type errors.
```

---

## 第四步：观察处理流程

### 查看服务日志
服务终端会显示完整处理流程：
```
webhook.received          github_event=issues action=opened
issue.analyzing           owner=test-org repo=test-repo number=1
llm.analyzing_code        model=qwen3-coder:30b
fix.generating            files=1
pr.creating               title="Fix: Replace print with logging"
pr.created                pr_url=https://github.com/.../pull/2
```

### 查看 GitHub
1. 进入你的测试仓库
2. 查看 **Pull requests** 标签
3. 应该能看到 Agent 创建的 PR

---

## 第五步：人工确认模式（如配置为 manual）

如果配置为 `CONFIRM_MODE=manual`：

1. Agent 会在 Issue 下评论：
   ```
   我已分析此问题，建议修复方案如下：
   
   [修复详情...]
   
   回复 `@github-agent confirm` 确认创建 PR
   回复 `@github-agent cancel` 取消
   ```

2. 你回复 `@github-agent confirm`

3. Agent 创建 PR

---

## 第六步：验证修复质量

### 检查 PR 内容
- 修复是否正确
- 是否只修改了必要的代码
- 是否符合项目风格

### 测试 PR
```bash
git fetch origin pull/2/head:pr-test
git checkout pr-test
python hello.py
```

---

## 常见问题

### Q: Webhook 显示 401 Unauthorized
- 检查 `GITHUB_WEBHOOK_SECRET` 是否与 GitHub 配置一致
- 查看服务日志确认收到请求

### Q: Webhook 显示 404 Not Found
- 检查 URL 是否正确（需以 `/webhook` 结尾）
- 确认服务正在运行

### Q: 收到 Webhook 但没有创建 PR
- 检查 Ollama 是否正常运行
- 查看服务日志中的错误信息
- 检查 GitHub Token 权限（需要 `repo` 权限）

### Q: PR 创建失败
```
github_api.error  status=403 message="Resource not accessible by personal access token"
```
- Token 需要 `repo` 权限（如果是私有仓库）
- 对于 Fork 的仓库，需要额外的权限

---

## 验证清单

- [ ] Webhook 显示绿色勾选（Recent Deliveries）
- [ ] 服务日志显示 `webhook.received`
- [ ] Issue 被正确分析
- [ ] PR 被创建（或收到确认请求）
- [ ] PR 内容正确

测试通过后，你的 GitHub Agent 就可以正式工作了！
