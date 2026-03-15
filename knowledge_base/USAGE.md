# 成功案例存储 - 使用说明

## 快速开始

### 1. 自动保存案例（已集成到 CodeExecutor）

代码修改成功后，案例会自动保存到本地知识库：

```python
from code_executor.code_executor import CodeExecutor

# 创建执行器（案例存储自动启用）
executor = CodeExecutor(...)

# 执行任务
result = executor.execute_task(
    task_type="fix_issue",
    instruction="Fix analogRead noise on A0",
    repo_full_name="owner/arduino-project",
    issue_number=42,
    ...
)

# 执行成功后，案例会自动保存到 knowledge_base/data/cases/
```

### 2. 手动管理案例

```python
from knowledge_base.success_case_store import (
    SuccessCaseStore, SuccessCase, 
    IssueInfo, SolutionInfo, OutcomeInfo
)

# 创建存储实例
store = SuccessCaseStore()

# 创建案例
case = SuccessCase(
    repository="owner/project",
    issue=IssueInfo(
        title="Fix sensor noise",
        body="A0 readings are noisy",
        keywords=["analogRead", "A0"],
        language="arduino"
    ),
    solution=SolutionInfo(
        description="Add moving average filter",
        approach="filter"
    ),
    outcome=OutcomeInfo(success=True)
)

# 保存
case_id = store.save_case(case)
print(f"案例已保存: {case_id}")

# 加载
loaded = store.load_case(case_id)
print(loaded.get_summary())

# 查找相似案例
similar = store.find_similar_cases(
    "sensor noise filtering",
    top_k=3
)
for case, similarity in similar:
    print(f"{case.case_id}: {similarity:.2f}")
```

### 3. 案例数据结构

```json
{
  "case_id": "case_20260312_a1b2c3",
  "repository": "owner/arduino-project",
  "issue": {
    "title": "Fix analogRead noise on A0",
    "keywords": ["analogRead", "A0", "noise"],
    "language": "arduino"
  },
  "solution": {
    "description": "Add moving average filter",
    "files_modified": ["sensor.ino"],
    "arduino_specific": {
      "pins_involved": ["A0"],
      "libraries_used": ["Wire"]
    }
  },
  "outcome": {
    "success": true,
    "pr_merged": true
  }
}
```

## 存储位置

案例存储在 `knowledge_base/data/cases/` 目录：

```
knowledge_base/data/cases/
├── index.json          # 案例索引
├── 2026/
│   └── 03/
│       ├── case_20260312_001.json
│       └── case_20260312_002.json
```

## Phase 2: 推送到资料仓库（已完成）

### 自动同步配置

在 `.env` 文件中配置：

```bash
# 资料仓库配置
KNOWLEDGE_REPO_URL=https://github.com/owner/knowledge-base
GITHUB_TOKEN=ghp_your_token_here

# 同步间隔（秒，默认1800=30分钟）
KNOWLEDGE_SYNC_INTERVAL=1800
```

### 同步流程

案例保存后自动触发同步：

```
代码修改成功
    ↓
保存案例到本地知识库
    ↓
自动触发异步同步
    ↓
推送到资料仓库 (GitHub API)
    ↓
更新同步状态
```

### 手动管理同步

```python
from knowledge_base.knowledge_sync import KnowledgeSyncManager

# 初始化同步管理器
sync = KnowledgeSyncManager(
    knowledge_repo_url="https://github.com/owner/knowledge-base",
    local_kb_path="/path/to/kb",
    github_token="ghp_xxx"
)

# 同步单个案例
sync.sync_case("case_20260312_xxx")

# 批量同步所有待处理案例
success, failed = sync.sync_all_pending()
print(f"同步完成: 成功 {success}, 失败 {failed}")

# 从远程拉取知识库（新环境初始化）
sync.pull_from_remote(sync_mode="full")

# 查看同步状态
summary = sync.get_sync_summary()
print(f"待同步: {summary['pending_count']}")
print(f"已同步: {summary['synced_count']}")
```

### 新环境初始化

在新部署的 Agent 上拉取知识库：

```python
from knowledge_base.knowledge_sync import create_sync_manager

# 创建管理器
sync = create_sync_manager()

# 初始化（拉取全部知识）
sync.initialize_new_environment(sync_mode="full")

# 或只拉取最近30天的案例
# sync.initialize_new_environment(sync_mode="recent")

# 或只拉取模式库（最小化）
# sync.initialize_new_environment(sync_mode="minimal")
```

---

## 向量检索测试

### 使用命令行工具

```bash
# 查看知识库统计信息（包含 HNSW 配置）
python scripts/kb_query.py -s

# 测试向量检索
python scripts/kb_query.py "芯片参数查询" -k 5

# 性能测试
python scripts/kb_query.py "测试查询" --perf
```

### 使用 Python API

```python
from knowledge_base.kb_service import KnowledgeBaseService
import time

# 创建服务实例
kb = KnowledgeBaseService()

# 测试查询
queries = ["SAMD21 规格", "GPIO 配置", "I2C 协议"]

for q in queries:
    start = time.time()
    result = kb.query(q, top_k=3)
    elapsed = (time.time() - start) * 1000
    
    print(f"查询: {q}")
    print(f"  找到: {result['total_found']} 条结果")
    print(f"  耗时: {elapsed:.2f}ms")
    
    for r in result['results']:
        print(f"  - {r['metadata'].get('source', 'unknown')}: {r['similarity']:.3f}")

# 查看向量存储统计
stats = kb.get_stats()
print(f"\n向量存储: {stats.get('vector_store', {})}")
```

### 预期性能指标

| 指标 | HNSW 模式 | 简单模式 |
|------|----------|---------|
| 单次查询耗时 | < 1ms | 10-200ms |
| 支持的文档数 | 10万+ | < 5000 |
| 内存占用 | 中等 | 低 |

**注意**: 如果 `hnswlib` 未安装，系统会自动降级到简单模式（暴力搜索）。
