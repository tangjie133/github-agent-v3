#!/usr/bin/env python3
"""
成功案例存储 (Success Case Store)

负责：
1. 存储成功案例到本地知识库
2. 生成案例向量嵌入
3. 检索相似案例
4. 导出案例到资料仓库

方案A - Phase 1 实现
"""

import json
import uuid
import hashlib
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from dataclasses import dataclass, field, asdict

# 尝试导入 numpy 用于向量运算
try:
    import numpy as np
    HAS_NUMPY = True
except ImportError:
    HAS_NUMPY = False

logger = logging.getLogger(__name__)


@dataclass
class IssueInfo:
    """Issue 信息"""
    title: str
    body: str
    keywords: List[str] = field(default_factory=list)
    embedding: List[float] = field(default_factory=list)
    language: str = "unknown"  # python, arduino, cpp
    complexity: str = "simple"  # simple, medium, complex
    
    def to_dict(self) -> Dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'IssueInfo':
        return cls(**data)


@dataclass
class CodeChange:
    """代码变更"""
    type: str  # add, modify, delete
    description: str
    search_context: str = ""  # SEARCH 文本
    replacement: str = ""  # REPLACE 文本


@dataclass
class FileModification:
    """文件修改"""
    path: str
    language: str
    changes: List[CodeChange] = field(default_factory=list)


@dataclass
class CodePattern:
    """代码模式"""
    pattern_type: str
    description: str
    search_context: str
    replacement_template: str
    parameters: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ArduinoSpecific:
    """Arduino 特定信息"""
    pins_involved: List[str] = field(default_factory=list)
    libraries_used: List[str] = field(default_factory=list)
    libraries_added: List[str] = field(default_factory=list)
    memory_impact: str = "unknown"  # low, medium, high


@dataclass
class SolutionInfo:
    """解决方案信息"""
    description: str
    approach: str  # filter, fix, refactor, add_feature
    files_modified: List[FileModification] = field(default_factory=list)
    code_pattern: Optional[CodePattern] = None
    arduino_specific: Optional[ArduinoSpecific] = None
    
    def to_dict(self) -> Dict:
        result = asdict(self)
        # 处理嵌套 dataclass
        if self.code_pattern:
            result['code_pattern'] = asdict(self.code_pattern)
        if self.arduino_specific:
            result['arduino_specific'] = asdict(self.arduino_specific)
        return result


@dataclass
class OutcomeInfo:
    """结果信息"""
    success: bool
    pr_number: Optional[int] = None
    pr_merged: bool = False
    user_feedback: str = ""  # positive, neutral, negative
    test_results: str = ""  # passed, failed, unknown
    
    def to_dict(self) -> Dict:
        return asdict(self)


@dataclass
class SuccessCase:
    """
    成功案例
    
    这是知识增强的核心数据结构，记录一个完整的修复案例
    """
    schema_version: str = "1.0"
    case_id: str = field(default_factory=lambda: f"case_{datetime.now().strftime('%Y%m%d')}_{uuid.uuid4().hex[:6]}")
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    repository: str = ""
    
    issue: IssueInfo = field(default_factory=lambda: IssueInfo("", ""))
    solution: SolutionInfo = field(default_factory=lambda: SolutionInfo("", ""))
    outcome: OutcomeInfo = field(default_factory=lambda: OutcomeInfo(True))
    
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def __post_init__(self):
        """初始化后处理"""
        if not self.metadata:
            self.metadata = {
                "agent_version": "2.1.0",
                "model_used": "qwen3-coder:30b",
                "confidence_score": 0.0,
                "reviewed_by_human": False
            }
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为字典（用于 JSON 序列化）"""
        return {
            "schema_version": self.schema_version,
            "case_id": self.case_id,
            "created_at": self.created_at,
            "repository": self.repository,
            "issue": self.issue.to_dict(),
            "solution": self.solution.to_dict(),
            "outcome": self.outcome.to_dict(),
            "metadata": self.metadata
        }
    
    @classmethod
    def from_dict(cls, data: Dict) -> 'SuccessCase':
        """从字典创建实例"""
        case = cls(
            schema_version=data.get("schema_version", "1.0"),
            case_id=data.get("case_id", ""),
            created_at=data.get("created_at", ""),
            repository=data.get("repository", ""),
            metadata=data.get("metadata", {})
        )
        
        # 解析嵌套结构
        if "issue" in data:
            case.issue = IssueInfo.from_dict(data["issue"])
        if "solution" in data:
            solution_data = data["solution"]
            
            # 解析 files_modified
            files_modified = []
            for fm in solution_data.get("files_modified", []):
                if fm:  # 确保不是 None
                    changes = []
                    for c in fm.get("changes", []):
                        if c:  # 确保不是 None
                            changes.append(CodeChange(
                                type=c.get("type", ""),
                                description=c.get("description", ""),
                                search_context=c.get("search_context", ""),
                                replacement=c.get("replacement", "")
                            ))
                    files_modified.append(FileModification(
                        path=fm.get("path", ""),
                        language=fm.get("language", ""),
                        changes=changes
                    ))
            
            case.solution = SolutionInfo(
                description=solution_data.get("description", ""),
                approach=solution_data.get("approach", ""),
                files_modified=files_modified
            )
            
            # 解析 code_pattern
            cp = solution_data.get("code_pattern")
            if cp:
                case.solution.code_pattern = CodePattern(
                    pattern_type=cp.get("pattern_type", ""),
                    description=cp.get("description", ""),
                    search_context=cp.get("search_context", ""),
                    replacement_template=cp.get("replacement_template", ""),
                    parameters=cp.get("parameters", {})
                )
            
            # 解析 arduino_specific
            ar = solution_data.get("arduino_specific")
            if ar:
                case.solution.arduino_specific = ArduinoSpecific(
                    pins_involved=ar.get("pins_involved", []),
                    libraries_used=ar.get("libraries_used", []),
                    libraries_added=ar.get("libraries_added", []),
                    memory_impact=ar.get("memory_impact", "unknown")
                )
        
        if "outcome" in data:
            case.outcome = OutcomeInfo(**data["outcome"])
        
        return case
    
    def get_summary(self) -> str:
        """获取案例摘要"""
        return f"""
案例 {self.case_id}
仓库: {self.repository}
问题: {self.issue.title}
方案: {self.solution.description}
状态: {'成功' if self.outcome.success else '失败'}
时间: {self.created_at}
""".strip()


class SuccessCaseStore:
    """
    成功案例存储管理器
    
    负责案例的存储、检索和管理
    """
    
    def __init__(self, 
                 storage_path: Path = None,
                 embedding_generator=None):
        """
        初始化存储管理器
        
        Args:
            storage_path: 本地存储路径，默认项目目录下的 knowledge_base/data/cases
            embedding_generator: 嵌入生成器，用于生成向量
        """
        if storage_path is None:
            storage_path = Path(__file__).parent / "data" / "cases"
        
        self.storage_path = Path(storage_path)
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.embedding_generator = embedding_generator
        self._case_cache: Dict[str, SuccessCase] = {}
        self._embedding_cache: Dict[str, List[float]] = {}
        
        logger.debug(f"[SuccessCaseStore] 初始化完成，存储路径: {self.storage_path}")
        
        # 加载现有案例索引
        self._load_index()
    
    # ============================================================================
    # 核心操作
    # ============================================================================
    
    def save_case(self, case: SuccessCase) -> str:
        """
        保存案例
        
        Args:
            case: 成功案例
            
        Returns:
            case_id
        """
        logger.info(f"[SuccessCaseStore] 保存案例: {case.case_id}")
        logger.debug(f"[SuccessCaseStore]   仓库: {case.repository}")
        logger.debug(f"[SuccessCaseStore]   问题: {case.issue.title[:50]}...")
        
        # 1. 确保有 embedding
        if not case.issue.embedding and self.embedding_generator:
            logger.debug(f"[SuccessCaseStore]   生成 embedding...")
            case.issue.embedding = self._generate_embedding(
                f"{case.issue.title}\n{case.issue.body}"
            )
            logger.debug(f"[SuccessCaseStore]   embedding 维度: {len(case.issue.embedding)}")
        
        # 2. 生成文件路径（按年月组织）
        file_path = self._get_case_file_path(case)
        file_path.parent.mkdir(parents=True, exist_ok=True)
        
        # 3. 保存到文件
        case_data = case.to_dict()
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(case_data, f, indent=2, ensure_ascii=False)
        
        logger.debug(f"[SuccessCaseStore]   保存到: {file_path}")
        
        # 4. 更新缓存和索引
        self._case_cache[case.case_id] = case
        if case.issue.embedding:
            self._embedding_cache[case.case_id] = case.issue.embedding
        self._update_index(case)
        
        logger.info(f"[SuccessCaseStore] ✅ 案例保存成功: {case.case_id}")
        return case.case_id
    
    def load_case(self, case_id: str) -> Optional[SuccessCase]:
        """
        加载案例
        
        Args:
            case_id: 案例ID
            
        Returns:
            SuccessCase 或 None
        """
        # 先检查缓存
        if case_id in self._case_cache:
            return self._case_cache[case_id]
        
        # 从文件加载
        file_path = self._find_case_file(case_id)
        if not file_path or not file_path.exists():
            logger.warning(f"[SuccessCaseStore] 案例不存在: {case_id}")
            return None
        
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            case = SuccessCase.from_dict(data)
            self._case_cache[case_id] = case
            if case.issue.embedding:
                self._embedding_cache[case_id] = case.issue.embedding
            return case
        except Exception as e:
            logger.error(f"[SuccessCaseStore] 加载案例失败 {case_id}: {e}")
            return None
    
    def find_similar_cases(self, 
                          query_text: str,
                          top_k: int = 3,
                          min_similarity: float = 0.75) -> List[Tuple[SuccessCase, float]]:
        """
        查找相似案例
        
        Args:
            query_text: 查询文本
            top_k: 返回前 K 个结果
            min_similarity: 最小相似度阈值
            
        Returns:
            [(案例, 相似度), ...]
        """
        logger.info(f"[SuccessCaseStore] 查找相似案例: '{query_text[:50]}...'")
        logger.debug(f"[SuccessCaseStore]   top_k={top_k}, min_similarity={min_similarity}")
        
        if not self.embedding_generator:
            logger.warning("[SuccessCaseStore] 未配置 embedding 生成器，无法搜索")
            return []
        
        # 1. 生成查询 embedding
        query_embedding = self._generate_embedding(query_text)
        logger.debug(f"[SuccessCaseStore]   查询 embedding 维度: {len(query_embedding)}")
        
        # 2. 计算相似度
        similarities = []
        for case_id, case_embedding in self._embedding_cache.items():
            similarity = self._cosine_similarity(query_embedding, case_embedding)
            if similarity >= min_similarity:
                similarities.append((case_id, similarity))
        
        # 3. 排序并取前 K
        similarities.sort(key=lambda x: x[1], reverse=True)
        top_results = similarities[:top_k]
        
        logger.info(f"[SuccessCaseStore]   找到 {len(top_results)} 个相似案例")
        
        # 4. 加载案例详情
        results = []
        for case_id, similarity in top_results:
            case = self.load_case(case_id)
            if case:
                results.append((case, similarity))
                logger.debug(f"[SuccessCaseStore]     - {case_id}: {similarity:.3f}")
        
        return results
    
    def get_all_cases(self, 
                     language: str = None,
                     limit: int = None) -> List[SuccessCase]:
        """
        获取所有案例（可选过滤）
        
        Args:
            language: 按语言过滤
            limit: 限制数量
            
        Returns:
            案例列表
        """
        cases = []
        index = self._load_index()
        
        for case_id in index.get("case_ids", []):
            case = self.load_case(case_id)
            if case:
                if language and case.issue.language != language:
                    continue
                cases.append(case)
        
        if limit:
            cases = cases[:limit]
        
        return cases
    
    # ============================================================================
    # 从代码执行结果创建案例
    # ============================================================================
    
    def create_case_from_execution(self,
                                   repo: str,
                                   issue_number: int,
                                   issue_title: str,
                                   issue_body: str,
                                   files_modified: List[str],
                                   original_contents: Dict[str, str],
                                   modified_contents: Dict[str, str],
                                   success: bool = True) -> SuccessCase:
        """
        从代码执行结果创建案例
        
        Args:
            repo: 仓库名
            issue_number: Issue 编号
            issue_title: Issue 标题
            issue_body: Issue 内容
            files_modified: 修改的文件列表
            original_contents: 原始内容 {file_path: content}
            modified_contents: 修改后内容 {file_path: content}
            success: 是否成功
            
        Returns:
            SuccessCase
        """
        logger.info(f"[SuccessCaseStore] 从执行结果创建案例: {repo}#{issue_number}")
        
        # 1. 提取关键词
        keywords = self._extract_keywords(issue_title, issue_body)
        logger.debug(f"[SuccessCaseStore]   提取关键词: {keywords}")
        
        # 2. 检测语言
        language = self._detect_language(files_modified)
        logger.debug(f"[SuccessCaseStore]   检测语言: {language}")
        
        # 3. 构建 IssueInfo
        issue = IssueInfo(
            title=issue_title,
            body=issue_body,
            keywords=keywords,
            language=language,
            complexity=self._estimate_complexity(files_modified)
        )
        
        # 4. 构建 SolutionInfo
        file_mods = []
        for file_path in files_modified:
            if file_path in original_contents and file_path in modified_contents:
                orig = original_contents[file_path]
                mod = modified_contents[file_path]
                
                # 提取变更
                changes = self._extract_changes(orig, mod)
                
                file_mods.append(FileModification(
                    path=file_path,
                    language=self._detect_file_language(file_path),
                    changes=changes
                ))
        
        # 尝试提取代码模式
        code_pattern = None
        if len(file_mods) == 1 and file_mods[0].changes:
            # 单文件修改，尝试提取模式
            main_change = file_mods[0].changes[0]
            if main_change.search_context and main_change.replacement:
                code_pattern = CodePattern(
                    pattern_type="generic_replace",
                    description="Direct replacement pattern",
                    search_context=main_change.search_context,
                    replacement_template=main_change.replacement
                )
        
        solution = SolutionInfo(
            description=f"Fixed {issue_title}",
            approach="fix",
            files_modified=file_mods,
            code_pattern=code_pattern
        )
        
        # 5. 提取 Arduino 特定信息
        if language == "arduino":
            solution.arduino_specific = self._extract_arduino_info(
                modified_contents
            )
        
        # 6. 构建 OutcomeInfo
        outcome = OutcomeInfo(
            success=success,
            pr_number=None,  # PR 创建后再更新
            pr_merged=False
        )
        
        # 7. 创建案例
        case = SuccessCase(
            repository=repo,
            issue=issue,
            solution=solution,
            outcome=outcome,
            metadata={
                "agent_version": "2.1.0",
                "model_used": "qwen3-coder:30b",
                "confidence_score": 0.85 if success else 0.0,
                "reviewed_by_human": False,
                "source_issue_number": issue_number
            }
        )
        
        logger.info(f"[SuccessCaseStore]   案例创建完成: {case.case_id}")
        return case
    
    # ============================================================================
    # 内部方法
    # ============================================================================
    
    def _get_case_file_path(self, case: SuccessCase) -> Path:
        """生成案例文件路径"""
        date = datetime.fromisoformat(case.created_at.replace('Z', '+00:00'))
        return self.storage_path / f"{date.year}" / f"{date.month:02d}" / f"{case.case_id}.json"
    
    def _find_case_file(self, case_id: str) -> Optional[Path]:
        """查找案例文件"""
        # 遍历所有子目录查找
        for json_file in self.storage_path.rglob(f"{case_id}.json"):
            return json_file
        return None
    
    def _generate_embedding(self, text: str) -> List[float]:
        """生成文本嵌入"""
        if self.embedding_generator:
            try:
                return self.embedding_generator.embed(text)
            except Exception as e:
                logger.error(f"[SuccessCaseStore] 生成 embedding 失败: {e}")
        
        # 降级：返回零向量（尝试获取正确维度，否则默认768）
        default_dim = 768
        if self.embedding_generator and hasattr(self.embedding_generator, '_get_dimension'):
            try:
                default_dim = self.embedding_generator._get_dimension()
            except Exception:
                pass
        return [0.0] * default_dim
    
    def _cosine_similarity(self, vec1: List[float], vec2: List[float]) -> float:
        """计算余弦相似度"""
        if not HAS_NUMPY or not vec1 or not vec2:
            return 0.0
        
        try:
            v1 = np.array(vec1)
            v2 = np.array(vec2)
            
            norm1 = np.linalg.norm(v1)
            norm2 = np.linalg.norm(v2)
            
            if norm1 == 0 or norm2 == 0:
                return 0.0
            
            return float(np.dot(v1, v2) / (norm1 * norm2))
        except Exception as e:
            logger.error(f"[SuccessCaseStore] 计算相似度失败: {e}")
            return 0.0
    
    def _load_index(self) -> Dict:
        """加载索引"""
        index_path = self.storage_path / "index.json"
        if index_path.exists():
            try:
                with open(index_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"[SuccessCaseStore] 加载索引失败: {e}")
        
        return {"case_ids": [], "last_updated": None}
    
    def _update_index(self, case: SuccessCase):
        """更新索引"""
        index = self._load_index()
        
        if case.case_id not in index["case_ids"]:
            index["case_ids"].append(case.case_id)
        
        index["last_updated"] = datetime.now().isoformat()
        index["total_cases"] = len(index["case_ids"])
        
        # 保存索引
        index_path = self.storage_path / "index.json"
        with open(index_path, 'w', encoding='utf-8') as f:
            json.dump(index, f, indent=2, ensure_ascii=False)
    
    def _extract_keywords(self, title: str, body: str) -> List[str]:
        """提取关键词（简化版）"""
        text = f"{title} {body}".lower()
        
        # Arduino 相关关键词
        arduino_keywords = [
            "analogread", "digitalwrite", "pinmode", "serial", "wire",
            "sensor", "pwm", "interrupt", "timer", "i2c", "spi"
        ]
        
        # Python 相关关键词
        python_keywords = [
            "error", "exception", "import", "class", "function",
            "async", "await", "decorator", "generator"
        ]
        
        found = []
        for kw in arduino_keywords + python_keywords:
            if kw in text:
                found.append(kw)
        
        return found[:10]  # 最多10个
    
    def _detect_language(self, files: List[str]) -> str:
        """检测编程语言"""
        extensions = [Path(f).suffix.lower() for f in files]
        
        if any(ext in ['.ino', '.cpp', '.c', '.h'] for ext in extensions):
            return "arduino" if '.ino' in extensions else "cpp"
        elif '.py' in extensions:
            return "python"
        
        return "unknown"
    
    def _detect_file_language(self, file_path: str) -> str:
        """检测单个文件语言"""
        ext = Path(file_path).suffix.lower()
        
        if ext == '.ino':
            return "arduino"
        elif ext == '.py':
            return "python"
        elif ext in ['.cpp', '.c', '.h']:
            return "cpp"
        
        return "unknown"
    
    def _estimate_complexity(self, files: List[str]) -> str:
        """估计复杂度"""
        if len(files) == 1:
            return "simple"
        elif len(files) <= 3:
            return "medium"
        else:
            return "complex"
    
    def _extract_changes(self, original: str, modified: str) -> List[CodeChange]:
        """提取变更内容（简化版）"""
        changes = []
        
        if original != modified:
            # 找到第一个不同的行
            orig_lines = original.split('\n')
            mod_lines = modified.split('\n')
            
            # 简化处理：记录前3行变化
            search = '\n'.join(orig_lines[:3])
            replace = '\n'.join(mod_lines[:3])
            
            changes.append(CodeChange(
                type="modify",
                description=f"Modified {len(orig_lines)} lines",
                search_context=search,
                replacement=replace
            ))
        
        return changes
    
    def _extract_arduino_info(self, contents: Dict[str, str]) -> ArduinoSpecific:
        """提取 Arduino 特定信息"""
        info = ArduinoSpecific()
        
        for content in contents.values():
            # 提取引脚
            import re
            pins = re.findall(r'(A\d+|pin\s*[=:]?\s*\d+)', content, re.IGNORECASE)
            info.pins_involved.extend(pins)
            
            # 提取库
            libs = re.findall(r'#include\s*[<"](\w+)', content)
            info.libraries_used.extend(libs)
        
        # 去重
        info.pins_involved = list(set(info.pins_involved))
        info.libraries_used = list(set(info.libraries_used))
        
        return info


# ================================================================================
# 便捷函数
# ================================================================================

def create_case_store(storage_path: Path = None) -> SuccessCaseStore:
    """创建案例存储实例"""
    # 尝试使用现有的嵌入生成器
    try:
        from .kb_service import SimpleEmbedding
        embedder = SimpleEmbedding()
    except Exception as e:
        logger.warning(f"[SuccessCaseStore] 无法创建嵌入生成器: {e}")
        embedder = None
    
    return SuccessCaseStore(storage_path, embedder)


if __name__ == "__main__":
    # 简单测试
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        store = SuccessCaseStore(Path(tmpdir))
        
        # 创建测试案例
        case = SuccessCase(
            repository="test/repo",
            issue=IssueInfo(
                title="Fix analogRead noise",
                body="The sensor on A0 is noisy",
                keywords=["analogRead", "A0", "noise"],
                language="arduino"
            ),
            solution=SolutionInfo(
                description="Add moving average filter",
                approach="filter",
                files_modified=[FileModification("sensor.ino", "arduino")]
            ),
            outcome=OutcomeInfo(success=True)
        )
        
        # 保存
        case_id = store.save_case(case)
        print(f"保存案例: {case_id}")
        
        # 加载
        loaded = store.load_case(case_id)
        print(f"加载案例: {loaded.case_id}")
        print(loaded.get_summary())
