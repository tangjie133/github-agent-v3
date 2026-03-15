#!/usr/bin/env python3
"""
知识库统一数据模型

所有文档类型（Markdown/PDF/TXT）使用统一的 metadata 结构
"""

from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional
from enum import Enum
from pathlib import Path


class DocType(str, Enum):
    """文档类型"""
    CHIP = "chip"           # 芯片文档
    PRACTICE = "practice"   # 最佳实践
    GUIDE = "guide"         # 教程指南
    UNKNOWN = "unknown"


class ContentType(str, Enum):
    """内容类型"""
    TEXT = "text"           # 普通文本
    TABLE = "table"         # 表格
    REGISTER = "register"   # 寄存器定义
    CODE = "code"           # 代码示例
    API = "api"             # API 文档


@dataclass
class ChunkMetadata:
    """
    统一的 Chunk Metadata 结构
    
    适用于所有文档类型（Markdown/PDF/TXT）
    """
    # 基础信息（所有文档类型都有）
    source: str                     # 来源文件路径
    doc_type: str                   # 文档类型: chip/practice/guide
    content_type: str = "text"      # 内容类型: text/table/register/code
    
    # 文件信息
    file_hash: str = ""             # 文件 MD5 hash（增量检测）
    chunk_hash: str = ""            # chunk 内容 hash（去重用）
    chunk_index: int = 0            # chunk 序号
    total_chunks: int = 0           # 总 chunks 数
    chunk_length: int = 0           # chunk 字符长度
    
    # 位置信息（PDF 特有，Markdown 可为空）
    page: int = 0                   # 页码（PDF）
    section: str = ""               # 章节标题
    section_level: int = 0          # 标题级别（1-6）
    
    # 语义标签（增强检索）
    tags: List[str] = field(default_factory=list)  # 关键词标签
    
    # 扩展信息（可选）
    vendor: str = ""                # 厂商（芯片文档）
    chip: str = ""                  # 芯片型号
    
    def to_dict(self) -> Dict[str, Any]:
        """转换为 ChromaDB 存储格式"""
        return {
            "source": self.source,
            "doc_type": self.doc_type,
            "content_type": self.content_type,
            "file_hash": self.file_hash,
            "chunk_hash": self.chunk_hash,
            "chunk_index": self.chunk_index,
            "total_chunks": self.total_chunks,
            "chunk_length": self.chunk_length,
            "page": self.page,
            "section": self.section,
            "section_level": self.section_level,
            "tags": ",".join(self.tags) if self.tags else "",
            "content_type": self.content_type.value if hasattr(self.content_type, 'value') else str(self.content_type),
            "vendor": self.vendor,
            "chip": self.chip,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ChunkMetadata":
        """从 ChromaDB 记录恢复"""
        tags_str = data.get("tags", "")
        return cls(
            source=data.get("source", ""),
            doc_type=data.get("doc_type", "unknown"),
            content_type=data.get("content_type", "text"),
            file_hash=data.get("file_hash", ""),
            chunk_hash=data.get("chunk_hash", ""),
            chunk_index=data.get("chunk_index", 0),
            total_chunks=data.get("total_chunks", 0),
            chunk_length=data.get("chunk_length", 0),
            page=data.get("page", 0),
            section=data.get("section", ""),
            section_level=data.get("section_level", 0),
            tags=tags_str.split(",") if tags_str else [],
            vendor=data.get("vendor", ""),
            chip=data.get("chip", ""),
        )


@dataclass
class DocumentChunk:
    """
    统一的文档 Chunk 结构
    
    所有文档类型（Markdown/PDF）都转换为这个结构
    """
    content: str                    # chunk 文本内容
    metadata: ChunkMetadata         # 统一 metadata
    embedding_id: str = ""          # 嵌入向量 ID（md5(content)）
    
    def __post_init__(self):
        """自动计算 chunk_hash 和 embedding_id"""
        import hashlib
        if not self.embedding_id:
            self.embedding_id = hashlib.md5(self.content.encode()).hexdigest()
        if not self.metadata.chunk_hash:
            self.metadata.chunk_hash = self.embedding_id
        if not self.metadata.chunk_length:
            self.metadata.chunk_length = len(self.content)


@dataclass
class Document:
    """
    源文档信息
    """
    source: Path                    # 文件路径
    doc_type: DocType               # 文档类型
    file_hash: str                  # 文件 hash
    chunks: List[DocumentChunk] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    # 提取的元数据（PDF 特有）
    vendor: str = ""
    chip: str = ""
    
    def __post_init__(self):
        """自动提取文件名元数据"""
        if not self.vendor and not self.chip:
            self._extract_from_filename()
    
    def _extract_from_filename(self):
        """从文件名提取 vendor 和 chip"""
        import re
        name = self.source.stem.lower()
        
        # 尝试匹配 vendor_chip 格式
        parts = name.replace('_datasheet', '').replace('-datasheet', '').split('_')
        
        if len(parts) >= 2:
            self.vendor = parts[0]
            self.chip = '_'.join(parts[1:])
            # 清理版本号
            self.chip = re.sub(r'_(v?\d+\.?\d*|rev\d+|r\d+)$', '', self.chip, flags=re.I)
        elif len(parts) == 1:
            self.chip = parts[0]


# 查询结果结构
@dataclass
class QueryResult:
    """查询返回结果"""
    content: str                    # chunk 内容
    metadata: ChunkMetadata         # metadata
    similarity: float               # 相似度分数
    summary: str = ""               # 内容摘要（可选）
    highlights: List[str] = field(default_factory=list)  # 高亮片段
