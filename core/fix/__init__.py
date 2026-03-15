"""
Fix Engine Module

多文件代码修复引擎
"""

from core.fix.engine import MultiFileFixEngine, get_fix_engine
from core.fix.models import (
    FixPlan, FixResult, FixStatus,
    FilePatch, FileLocation, ChangeType,
    ValidationResult
)

__all__ = [
    'MultiFileFixEngine',
    'get_fix_engine',
    'FixPlan',
    'FixResult',
    'FixStatus',
    'FilePatch',
    'FileLocation',
    'ChangeType',
    'ValidationResult',
]