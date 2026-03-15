# Week 2 开发总结：LLM 管理系统 + 邮件通知

## 完成情况

### ✅ 已完成功能

#### 1. LLM 管理器 (`core/llm/`)

**核心组件：**
- **`manager.py`** - 统一的 LLM 管理器
  - 三层策略：Ollama → OpenClaw → 模板生成器
  - 自动 fallback 机制
  - 性能和错误统计
  - 支持任务类型：intent/code/answer
  
- **`ollama_client.py`** - Ollama 专用客户端
  - 异步 HTTP 客户端 (aiohttp)
  - 并发控制（信号量限制 2 并发）
  - 模型管理（列出、拉取）
  - 健康检查
  - 流式输出支持
  
- **`openclaw_client.py`** - OpenClaw 客户端
  - OpenAI 兼容 API
  - 异步 HTTP 客户端
  - 并发控制（信号量限制 5 并发）
  - 健康检查
  
- **`template_generator.py`** - 模板生成器
  - 保底方案（当所有 LLM 都失败时使用）
  - 基于错误模式的修复建议
  - 自动响应模板
  - 总是可用

**配置支持：**
```yaml
llm:
  primary_provider: ollama
  fallback_provider: openclaw
  ollama_host: http://localhost:11434
  ollama_model_code: qwen3-coder:30b
  openclaw_enabled: true
```

#### 2. 邮件通知系统 (`core/notification/email.py`)

**功能：**
- SMTP 邮件发送
- 管理员通知（处理失败时）
- HTML 格式邮件模板
- 排队提示（带邮件选项）
- 单例模式管理

**使用场景：**
1. 当 Issue 处理失败时，发送邮件给管理员
2. 当 Issue 排队超时时，在 GitHub 评论中提供邮件选项

**配置：**
```yaml
notification:
  smtp_host: smtp.gmail.com
  smtp_port: 587
  smtp_user: ${SMTP_USER}
  smtp_password: ${SMTP_PASSWORD}
  admin_email: ${ADMIN_EMAIL}
```

#### 3. 测试覆盖

**测试文件：**
- `tests/core/test_llm_manager.py` - LLM 管理器测试
- `tests/core/test_email_notifier.py` - 邮件通知测试

**测试结果：**
```
20 passed, 4 skipped
```

**测试类型：**
- 单元测试（使用 Mock）
- 契约测试（需要真实服务，默认跳过）
- 健康检查测试
- Fallback 机制测试
- 单例模式测试

### 📁 新增文件结构

```
core/
├── llm/
│   ├── __init__.py
│   ├── manager.py          # LLM 管理器
│   ├── ollama_client.py    # Ollama 客户端
│   ├── openclaw_client.py  # OpenClaw 客户端
│   └── template_generator.py # 模板生成器
├── notification/
│   ├── __init__.py
│   └── email.py            # 邮件通知器
tests/
├── __init__.py             # 修复导入问题
├── core/
│   ├── __init__.py
│   ├── test_llm_manager.py
│   └── test_email_notifier.py
├── conftest.py             # Pytest 配置
└── pyproject.toml          # Pytest 设置
```

### 🔄 架构设计

```
┌─────────────────────────────────────────────────────────────┐
│                      LLM Manager                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌────────────────┐    ┌────────────────┐                  │
│  │   Ollama       │───▶│   OpenClaw     │                  │
│  │   (Primary)    │    │   (Fallback)   │                  │
│  │                │    │                │                  │
│  │  qwen3-coder:30b   │    kimi-k2.5        │                  │
│  │  GPU 32GB      │    │  Cloud API     │                  │
│  └────────────────┘    └────────────────┘                  │
│           │                      │                         │
│           ▼                      ▼                         │
│  ┌──────────────────────────────────────┐                 │
│  │     Template Generator               │                 │
│  │     (Last Resort)                    │                 │
│  └──────────────────────────────────────┘                 │
│                                                             │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   Email Notifier                            │
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────┐        ┌──────────────────┐          │
│  │  Admin Alert     │        │  Queue Notify    │          │
│  │  (on failure)    │        │  (in issue)      │          │
│  │                  │        │                  │          │
│  │  HTML Email      │        │  + mailto link   │          │
│  │  with details    │        │  + contact info  │          │
│  └──────────────────┘        └──────────────────┘          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 📊 性能指标

| 组件 | 并发限制 | 超时 | 用途 |
|------|----------|------|------|
| Ollama | 2 | 300s | 代码生成 |
| OpenClaw | 5 | 60s | Fallback |
| Template | 无 | 即时 | 保底方案 |

### 🚀 使用示例

**生成代码修复：**
```python
from core.llm import get_llm_manager

manager = await get_llm_manager()
response = await manager.generate(
    prompt="Fix this Python error...",
    task_type="code"
)
print(response.text)  # 修复后的代码
```

**通知管理员：**
```python
from core.notification.email import get_email_notifier

notifier = get_email_notifier()
await notifier.notify_admin(
    issue_number=123,
    repo="owner/repo",
    issue_title="Bug",
    issue_body="...",
    failure_reason="API timeout"
)
```

### ⚠️ 已知问题

1. **DeprecationWarning**: `datetime.utcnow()` 已弃用（来自 core/logging.py）
   - 非关键问题，可以后续修复

2. **契约测试跳过**: 需要真实服务（Ollama/OpenClaw）
   - 标记为 `@pytest.mark.skip`
   - 手动运行时需要设置环境变量

### 📅 下一步计划

1. **集成测试** - 将 LLM 管理器集成到 Issue 处理流程
2. **监控指标** - 添加 LLM 调用指标收集（延迟、成功率）
3. **缓存层** - 为相似查询添加结果缓存
4. **错误模式优化** - 扩展模板生成器的错误模式库