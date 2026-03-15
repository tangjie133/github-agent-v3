"""
修复引擎数据模型
"""

from typing import List, Optional, Dict, Any
from dataclasses import dataclass, field
from enum import Enum


class ChangeType(Enum):
    """变更类型"""
    ADD = "add"
    MODIFY = "modify"
    DELETE = "delete"
    RENAME = "rename"


class FixStatus(Enum):
    """修复状态"""
    PENDING = "pending"
    ANALYZING = "analyzing"
    GENERATING = "generating"
    VALIDATING = "validating"
    READY = "ready"
    APPLIED = "applied"
    FAILED = "failed"


@dataclass
class FileLocation:
    """文件位置信息"""
    path: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    snippet: str = ""  # 相关代码片段


@dataclass
class FilePatch:
    """文件补丁"""
    path: str
    change_type: ChangeType
    old_content: Optional[str] = None  # 原内容（modify/delete）
    new_content: Optional[str] = None  # 新内容（add/modify）
    old_path: Optional[str] = None     # 原路径（rename）
    description: str = ""              # 修改说明
    
    def to_diff(self) -> str:
        """生成 diff 格式"""
        if self.change_type == ChangeType.ADD:
            return f"--- /dev/null\n+++ b/{self.path}\n" + self._format_add()
        elif self.change_type == ChangeType.DELETE:
            return f"--- a/{self.path}\n+++ /dev/null\n" + self._format_delete()
        elif self.change_type == ChangeType.MODIFY:
            return f"--- a/{self.path}\n+++ b/{self.path}\n" + self._format_modify()
        return ""
    
    def _format_add(self) -> str:
        lines = self.new_content.split('\n') if self.new_content else []
        result = [f"@@ -0,0 +1,{len(lines)} @@"]
        for line in lines:
            result.append(f"+{line}")
        return '\n'.join(result)
    
    def _format_delete(self) -> str:
        lines = self.old_content.split('\n') if self.old_content else []
        result = [f"@@ -1,{len(lines)} +0,0 @@"]
        for line in lines:
            result.append(f"-{line}")
        return '\n'.join(result)
    
    def _format_modify(self) -> str:
        # 简化版，实际应使用 diff 算法
        old_lines = self.old_content.split('\n') if self.old_content else []
        new_lines = self.new_content.split('\n') if self.new_content else []
        return f"@@ -1,{len(old_lines)} +1,{len(new_lines)} @@\n[diff content]"


@dataclass
class FixPlan:
    """修复计划"""
    issue_number: int
    repo: str
    title: str = ""
    description: str = ""
    affected_files: List[FileLocation] = field(default_factory=list)
    patches: List[FilePatch] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)  # 依赖的文件
    estimated_effort: str = "small"  # small/medium/large
    confidence: float = 0.0  # 0-1
    status: FixStatus = FixStatus.PENDING
    error_analysis: str = ""  # 错误分析
    fix_strategy: str = ""    # 修复策略
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "issue_number": self.issue_number,
            "repo": self.repo,
            "title": self.title,
            "description": self.description,
            "affected_files": [f.path for f in self.affected_files],
            "patch_count": len(self.patches),
            "dependencies": self.dependencies,
            "estimated_effort": self.estimated_effort,
            "confidence": self.confidence,
            "status": self.status.value,
        }


@dataclass
class ValidationResult:
    """验证结果"""
    is_valid: bool
    errors: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    
    def merge(self, other: 'ValidationResult'):
        """合并另一个验证结果"""
        self.is_valid = self.is_valid and other.is_valid
        self.errors.extend(other.errors)
        self.warnings.extend(other.warnings)


@dataclass
class FixResult:
    """修复执行结果"""
    success: bool
    plan: Optional[FixPlan] = None
    pr_number: Optional[int] = None
    branch_name: Optional[str] = None
    commit_sha: Optional[str] = None
    message: str = ""
    error: Optional[str] = None
    duration_seconds: float = 0.0
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "pr_number": self.pr_number,
            "branch_name": self.branch_name,
            "commit_sha": self.commit_sha,
            "message": self.message,
            "error": self.error,
            "duration_seconds": self.duration_seconds,
        }