"""
模板生成器

当所有 LLM 都不可用时使用
提供基本的代码修复模板
"""

from typing import Dict, Any, List
from datetime import datetime

from core.logging import get_logger

logger = get_logger(__name__)


class TemplateGenerator:
    """
    模板生成器
    
    基于简单的规则生成修复建议
    用于 LLM 完全不可用时的保底方案
    """
    
    # 常见错误模式到修复的映射
    ERROR_PATTERNS: Dict[str, str] = {
        "TypeError: .* takes .* positional arguments but .* were given": 
            "检查函数调用时的参数数量，确保与函数定义匹配。",
        "IndexError: list index out of range":
            "检查列表索引是否超出范围，添加边界检查。",
        "KeyError: .*":
            "使用 .get() 方法替代直接访问字典，或添加键存在性检查。",
        "AttributeError: 'NoneType' object has no attribute":
            "添加空值检查，确保对象不为 None 后再访问属性。",
        "ImportError: No module named":
            "安装缺失的依赖包，或检查模块名称拼写。",
        "SyntaxError: invalid syntax":
            "检查 Python 语法，特别是括号、缩进和关键字。",
        "NameError: name .* is not defined":
            "检查变量名拼写，确保变量已定义。",
        "ZeroDivisionError: division by zero":
            "添加除数为零的检查。",
        "FileNotFoundError":
            "检查文件路径是否正确，确保文件存在。",
        "ValueError: invalid literal for int()":
            "添加输入验证，确保字符串可以正确转换为整数。",
    }
    
    def __init__(self):
        pass
    
    async def generate_fix(self,
                          issue_title: str,
                          issue_body: str,
                          error_logs: str = "",
                          file_context: List[Dict[str, Any]] = None) -> str:
        """
        基于模板生成修复建议
        
        Args:
            issue_title: Issue 标题
            issue_body: Issue 内容
            error_logs: 错误日志
            file_context: 相关文件上下文
        
        Returns:
            修复建议 Markdown
        """
        suggestions = []
        
        # 匹配错误模式
        for pattern, suggestion in self.ERROR_PATTERNS.items():
            import re
            if re.search(pattern, error_logs + issue_body + issue_title, re.IGNORECASE):
                suggestions.append(suggestion)
        
        # 如果没有匹配到，提供通用建议
        if not suggestions:
            suggestions.append("请仔细检查代码逻辑，添加适当的错误处理。")
            suggestions.append("查看错误日志以确定具体问题所在。")
            suggestions.append("检查相关的单元测试，确保测试覆盖此场景。")
        
        # 生成报告
        report = f"""## 📝 代码修复建议（模板生成）

> ⚠️ **注意**：由于 LLM 服务暂时不可用，此报告由模板生成器基于规则生成。

### 问题概述
**标题**: {issue_title}

**时间**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}

---

### 自动分析

基于错误模式匹配，发现以下可能的问题：

"""
        for i, suggestion in enumerate(suggestions, 1):
            report += f"{i}. {suggestion}\n"
        
        report += f"""
---

### 建议操作

1. **查看原始错误日志**
   ```
   {error_logs[:500] if error_logs else "无错误日志"}{'...' if len(error_logs) > 500 else ''}
   ```

2. **检查相关文件**
   {self._format_file_context(file_context)}

3. **手动修复建议**
   - 添加适当的错误处理（try-except）
   - 验证输入参数
   - 检查边界条件
   - 添加日志输出以便调试

4. **测试修复**
   - 运行相关单元测试
   - 手动验证修复是否解决了问题

---

### 需要人工介入

由于当前 LLM 服务不可用，强烈建议：

- 检查是否有服务故障（Ollama / OpenClaw）
- 手动分析问题并提交修复
- 联系系统管理员检查 LLM 服务状态

---

**提交建议**: 管理员 - 请检查 LLM 服务状态
"""
        
        return report
    
    def _format_file_context(self, file_context: List[Dict[str, Any]] = None) -> str:
        """格式化文件上下文"""
        if not file_context:
            return "无相关文件信息"
        
        result = []
        for file in file_context[:5]:  # 最多显示5个文件
            path = file.get("path", "未知")
            content = file.get("content", "")
            snippet = content[:200].replace("\n", " ") if content else ""
            result.append(f"   - `{path}`: {snippet}...")
        
        return "\n".join(result)
    
    async def generate_response(self,
                               prompt: str,
                               system: str = "") -> str:
        """
        通用响应接口
        
        当 LLM 不可用时返回模板响应
        """
        logger.warning("template.generator.used", 
                      prompt_preview=prompt[:100])
        
        return f"""## 🤖 自动响应（模板生成）

很抱歉，由于当前 AI 服务暂时不可用，我无法提供完整的智能分析。

### 您的请求
```
{prompt[:500]}
```

### 临时建议

1. **检查服务状态**: 请联系管理员确认 Ollama 和 OpenClaw 服务是否正常运行
2. **稍后重试**: 服务恢复后可以重新提交请求
3. **手动处理**: 对于紧急问题，建议手动分析并处理

### 联系支持

如需紧急帮助，请：
- 查看系统日志了解详细错误
- 联系系统管理员
- 参考项目文档自行处理

---
*生成时间: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}*
"""
    
    async def health_check(self) -> bool:
        """模板生成器总是可用"""
        return True