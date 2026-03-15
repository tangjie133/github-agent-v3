"""
多文件修复引擎

功能：
- 分析 Issue 并识别需要修改的文件
- 生成多文件补丁
- 验证补丁正确性
- 应用补丁
"""

import asyncio
import time
from typing import List, Optional, Dict, Any
from pathlib import Path

from core.logging import get_logger, traced
from core.config import get_config
from core.llm import get_llm_manager
from core.fix.models import (
    FixPlan, FixResult, FixStatus, FilePatch, FileLocation,
    ChangeType, ValidationResult
)
from core.i18n import t_detect

logger = get_logger(__name__)


class MultiFileFixEngine:
    """
    多文件修复引擎
    
    支持跨文件依赖的复杂修复
    """
    
    def __init__(self):
        self.config = get_config()
        self.llm = None  # 延迟初始化
    
    async def _get_llm(self):
        """获取 LLM 管理器"""
        if self.llm is None:
            self.llm = await get_llm_manager()
        return self.llm
    
    @traced("fix.analyze")
    async def analyze_issue(self,
                           issue_number: int,
                           repo: str,
                           issue_title: str,
                           issue_body: str,
                           error_logs: str = "",
                           repo_path: Optional[Path] = None) -> FixPlan:
        """
        分析 Issue，生成修复计划
        
        步骤：
        1. 使用 LLM 分析错误原因
        2. 识别受影响文件
        3. 分析文件间依赖
        4. 生成修复策略
        """
        logger.info("fix.analyze_start",
                   repo=repo,
                   issue=issue_number,
                   title=issue_title)
        
        plan = FixPlan(
            issue_number=issue_number,
            repo=repo,
            title=issue_title,
            status=FixStatus.ANALYZING
        )
        
        # 构建分析提示词
        prompt = self._build_analysis_prompt(
            issue_title, issue_body, error_logs, repo_path
        )
        
        llm = await self._get_llm()
        response = await llm.generate(
            prompt=prompt,
            task_type="code"
        )
        
        # 解析 LLM 响应
        analysis = self._parse_analysis_response(response.text)
        
        plan.error_analysis = analysis.get("error_analysis", "")
        plan.fix_strategy = analysis.get("fix_strategy", "")
        plan.affected_files = [
            FileLocation(path=p, snippet="") 
            for p in analysis.get("affected_files", [])
        ]
        plan.dependencies = analysis.get("dependencies", [])
        plan.estimated_effort = analysis.get("effort", "small")
        plan.confidence = analysis.get("confidence", 0.5)
        
        logger.info("fix.analyze_complete",
                   repo=repo,
                   issue=issue_number,
                   files=len(plan.affected_files),
                   confidence=plan.confidence)
        
        return plan
    
    @traced("fix.generate")
    async def generate_patches(self, plan: FixPlan, 
                               file_contents: Dict[str, str]) -> FixPlan:
        """
        为多个文件生成补丁
        
        Args:
            plan: 修复计划
            file_contents: 文件路径 -> 内容的映射
        
        Returns:
            更新后的修复计划（包含补丁）
        """
        logger.info("fix.generate_start",
                   repo=plan.repo,
                   issue=plan.issue_number,
                   file_count=len(plan.affected_files))
        
        plan.status = FixStatus.GENERATING
        
        # 按依赖顺序生成补丁
        files_to_process = self._sort_by_dependencies(
            plan.affected_files, plan.dependencies
        )
        
        for file_loc in files_to_process:
            path = file_loc.path
            content = file_contents.get(path, "")
            
            if not content and path in [f.path for f in plan.affected_files]:
                logger.warning("fix.file_content_missing", path=path)
                continue
            
            # 生成单个文件的补丁
            patch = await self._generate_single_patch(
                plan, path, content, file_contents
            )
            
            if patch:
                plan.patches.append(patch)
                logger.debug("fix.patch_generated", path=path)
        
        plan.status = FixStatus.VALIDATING
        
        logger.info("fix.generate_complete",
                   repo=plan.repo,
                   issue=plan.issue_number,
                   patch_count=len(plan.patches))
        
        return plan
    
    @traced("fix.validate")
    async def validate_patches(self, plan: FixPlan) -> ValidationResult:
        """
        验证补丁的正确性
        
        检查项：
        - 语法正确性
        - 依赖完整性
        - 无冲突
        """
        result = ValidationResult(is_valid=True)
        
        for patch in plan.patches:
            # 语法检查
            if patch.change_type == ChangeType.MODIFY:
                if not patch.old_content or not patch.new_content:
                    result.errors.append(f"{patch.path}: Missing content for modify")
                    result.is_valid = False
            
            elif patch.change_type == ChangeType.ADD:
                if not patch.new_content:
                    result.errors.append(f"{patch.path}: Missing content for add")
                    result.is_valid = False
            
            # TODO: 添加更多验证（如 Python 语法检查）
        
        # 检查依赖完整性
        patch_paths = {p.path for p in plan.patches}
        for dep in plan.dependencies:
            if dep not in patch_paths:
                result.warnings.append(f"Dependency not patched: {dep}")
        
        logger.info("fix.validation_complete",
                   repo=plan.repo,
                   issue=plan.issue_number,
                   is_valid=result.is_valid,
                   errors=len(result.errors),
                   warnings=len(result.warnings))
        
        return result
    
    @traced("fix.apply")
    async def apply_fix(self,
                       plan: FixPlan,
                       repo_path: Path,
                       git_ops=None) -> FixResult:
        """
        应用修复到仓库
        
        步骤：
        1. 创建分支
        2. 应用所有补丁
        3. 提交更改
        4. 推送分支
        """
        start_time = time.time()
        
        try:
            # 这里需要集成 Git 操作
            # 暂时返回模拟结果
            
            plan.status = FixStatus.APPLIED
            
            return FixResult(
                success=True,
                plan=plan,
                branch_name=f"issue-{plan.issue_number}-fix",
                message=t_detect("completed", plan.title),
                duration_seconds=time.time() - start_time
            )
            
        except Exception as e:
            plan.status = FixStatus.FAILED
            logger.error("fix.apply_failed",
                        repo=plan.repo,
                        issue=plan.issue_number,
                        error=str(e))
            
            return FixResult(
                success=False,
                plan=plan,
                error=str(e),
                duration_seconds=time.time() - start_time
            )
    
    def _build_analysis_prompt(self, title: str, body: str, 
                               error_logs: str, repo_path: Optional[Path]) -> str:
        """构建分析提示词"""
        return f"""Analyze this GitHub issue and identify what files need to be modified.

Issue Title: {title}

Issue Body:
```
{body}
```

Error Logs:
```
{error_logs}
```

Please analyze:
1. What is the root cause of the issue?
2. Which files need to be modified?
3. Are there dependencies between files?
4. What is the estimated effort (small/medium/large)?
5. What is your confidence level (0-1)?

Respond in this JSON format:
{{
    "error_analysis": "detailed analysis of the error",
    "fix_strategy": "high-level approach to fix",
    "affected_files": ["path/to/file1.py", "path/to/file2.py"],
    "dependencies": ["file1.py depends on file2.py"],
    "effort": "small|medium|large",
    "confidence": 0.85
}}"""
    
    def _parse_analysis_response(self, text: str) -> Dict[str, Any]:
        """解析 LLM 的分析响应"""
        import json
        import re
        
        # 尝试提取 JSON
        try:
            # 查找 JSON 块
            json_match = re.search(r'\{[\s\S]*\}', text)
            if json_match:
                return json.loads(json_match.group())
        except json.JSONDecodeError:
            pass
        
        # 如果解析失败，返回默认值
        logger.warning("fix.parse_analysis_failed", response_preview=text[:200])
        
        return {
            "error_analysis": "Failed to parse LLM response",
            "fix_strategy": "Manual review required",
            "affected_files": [],
            "dependencies": [],
            "effort": "small",
            "confidence": 0.0
        }
    
    async def _generate_single_patch(self, plan: FixPlan, path: str,
                                    content: str,
                                    all_contents: Dict[str, str]) -> Optional[FilePatch]:
        """生成单个文件的补丁"""
        
        prompt = f"""Generate a fix for this file:

File: {path}
Current content:
```python
{content}
```

Issue context:
{plan.error_analysis}

Fix strategy:
{plan.fix_strategy}

Related files context:
{self._format_related_files(path, all_contents)}

Please provide the complete fixed content for this file.
If the file should be deleted, respond with "DELETE".
If no changes needed, respond with "NO_CHANGE".

Fixed content:
"""
        
        llm = await self._get_llm()
        response = await llm.generate(prompt=prompt, task_type="code")
        
        new_content = response.text.strip()
        
        # 处理特殊响应
        if new_content == "DELETE":
            return FilePatch(
                path=path,
                change_type=ChangeType.DELETE,
                old_content=content,
                description="Deleted as part of fix"
            )
        
        if new_content == "NO_CHANGE":
            return None
        
        # 清理代码块标记
        if new_content.startswith("```python"):
            new_content = new_content[len("```python"):]
        if new_content.startswith("```"):
            new_content = new_content[len("```"):]
        if new_content.endswith("```"):
            new_content = new_content[:-len("```")]
        
        new_content = new_content.strip()
        
        # 确定变更类型
        if not content:
            change_type = ChangeType.ADD
        else:
            change_type = ChangeType.MODIFY
        
        return FilePatch(
            path=path,
            change_type=change_type,
            old_content=content if content else None,
            new_content=new_content,
            description=f"Fix for issue #{plan.issue_number}"
        )
    
    def _format_related_files(self, current_path: str, 
                              all_contents: Dict[str, str]) -> str:
        """格式化相关文件信息"""
        result = []
        for path, content in all_contents.items():
            if path != current_path:
                # 只显示前 50 行
                lines = content.split('\n')[:50]
                result.append(f"--- {path} ---")
                result.append('\n'.join(lines))
                if len(content.split('\n')) > 50:
                    result.append("... (truncated)")
        return '\n'.join(result) if result else "No related files"
    
    def _sort_by_dependencies(self, files: List[FileLocation],
                             dependencies: List[str]) -> List[FileLocation]:
        """
        按依赖顺序排序文件
        
        简单实现：先返回没有依赖的文件
        """
        # TODO: 实现拓扑排序
        return files


# 全局实例
_fix_engine: Optional[MultiFileFixEngine] = None


async def get_fix_engine() -> MultiFileFixEngine:
    """获取 FixEngine 实例"""
    global _fix_engine
    if _fix_engine is None:
        _fix_engine = MultiFileFixEngine()
    return _fix_engine