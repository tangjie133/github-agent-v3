#!/usr/bin/env python3
"""
统一文档处理器

支持：Markdown, PDF, TXT 等所有格式
统一接口：文件 → Chunks → Metadata → Embedding → ChromaDB
"""

import os
import re
import hashlib
import logging
from pathlib import Path
from typing import List, Optional, Dict, Any
from abc import ABC, abstractmethod

try:
    from .schema import Document, DocumentChunk, ChunkMetadata, DocType, ContentType
except ImportError:
    from schema import Document, DocumentChunk, ChunkMetadata, DocType, ContentType

logger = logging.getLogger(__name__)


class BaseParser(ABC):
    """文档解析器基类"""
    
    @abstractmethod
    def parse(self, file_path: Path, doc_type: DocType) -> Document:
        """
        解析文件为 Document 对象
        
        Args:
            file_path: 文件路径
            doc_type: 文档类型
            
        Returns:
            Document 对象（包含 chunks）
        """
        pass
    
    @abstractmethod
    def supports(self, file_path: Path) -> bool:
        """是否支持该文件格式"""
        pass


class MarkdownParser(BaseParser):
    """Markdown 文档解析器"""
    
    # Chunk 配置
    CHUNK_SIZE = 500
    CHUNK_OVERLAP = 80
    
    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() in ['.md', '.markdown', '.txt']
    
    def parse(self, file_path: Path, doc_type: DocType) -> Document:
        """解析 Markdown 为 Chunks"""
        content = file_path.read_text(encoding='utf-8')
        file_hash = hashlib.md5(content.encode()).hexdigest()
        
        # 创建 Document
        doc = Document(
            source=file_path,
            doc_type=doc_type,
            file_hash=file_hash
        )
        
        # 按标题分割为 sections
        sections = self._split_by_headers(content)
        
        # 每个 section 切分为 chunks
        chunk_index = 0
        for section_title, section_content, level in sections:
            chunks = self._create_chunks(
                content=section_content,
                section=section_title,
                section_level=level,
                file_path=file_path,
                doc_type=doc_type.value,
                file_hash=file_hash,
                start_index=chunk_index
            )
            doc.chunks.extend(chunks)
            chunk_index += len(chunks)
        
        # 更新 total_chunks
        for i, chunk in enumerate(doc.chunks):
            chunk.metadata.total_chunks = len(doc.chunks)
            chunk.metadata.chunk_index = i
        
        logger.info(f"📄 Markdown: {file_path.name} → {len(doc.chunks)} chunks")
        return doc
    
    def _split_by_headers(self, content: str) -> List[tuple]:
        """
        按 Markdown 标题分割文档
        
        Returns:
            [(title, content, level), ...]
        """
        # 匹配 Markdown 标题: # ## ###
        header_pattern = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
        
        sections = []
        current_title = ""
        current_content = []
        current_level = 0
        
        lines = content.split('\n')
        i = 0
        while i < len(lines):
            line = lines[i]
            match = header_pattern.match(line)
            
            if match:
                # 保存上一个 section
                if current_content:
                    sections.append((
                        current_title,
                        '\n'.join(current_content).strip(),
                        current_level
                    ))
                
                # 开始新 section
                current_level = len(match.group(1))
                current_title = match.group(2).strip()
                current_content = []
            else:
                current_content.append(line)
            
            i += 1
        
        # 保存最后一个 section
        if current_content:
            sections.append((
                current_title,
                '\n'.join(current_content).strip(),
                current_level
            ))
        
        # 如果没有标题，整个文档作为一个 section
        if not sections:
            sections.append(("", content.strip(), 0))
        
        return sections
    
    def _create_chunks(
        self,
        content: str,
        section: str,
        section_level: int,
        file_path: Path,
        doc_type: str,
        file_hash: str,
        start_index: int
    ) -> List[DocumentChunk]:
        """
        创建 chunks（带重叠）
        """
        chunks = []
        
        # 如果内容较短，直接作为一个 chunk
        if len(content) <= self.CHUNK_SIZE:
            metadata = ChunkMetadata(
                source=str(file_path),
                doc_type=doc_type,
                content_type=ContentType.TEXT,
                file_hash=file_hash,
                section=section,
                section_level=section_level,
                chunk_index=start_index,
            )
            # 自动提取 tags
            metadata.tags = self._extract_tags(content)
            
            chunks.append(DocumentChunk(
                content=content,
                metadata=metadata
            ))
            return chunks
        
        # 长内容需要切分
        # 优先按段落分割
        paragraphs = content.split('\n\n')
        current_chunk = []
        current_size = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            # 检查添加这段后是否超出限制
            if current_size + len(para) > self.CHUNK_SIZE and current_chunk:
                # 保存当前 chunk
                chunk_content = '\n\n'.join(current_chunk)
                metadata = ChunkMetadata(
                    source=str(file_path),
                    doc_type=doc_type,
                    content_type=ContentType.TEXT,
                    file_hash=file_hash,
                    section=section,
                    section_level=section_level,
                    chunk_index=start_index + len(chunks),
                )
                metadata.tags = self._extract_tags(chunk_content)
                
                chunks.append(DocumentChunk(
                    content=chunk_content,
                    metadata=metadata
                ))
                
                # 保留重叠部分
                overlap_text = self._get_overlap(current_chunk)
                current_chunk = [overlap_text, para] if overlap_text else [para]
                current_size = sum(len(p) for p in current_chunk)
            else:
                current_chunk.append(para)
                current_size += len(para)
        
        # 保存最后一个 chunk
        if current_chunk:
            chunk_content = '\n\n'.join(current_chunk)
            metadata = ChunkMetadata(
                source=str(file_path),
                doc_type=doc_type,
                content_type=ContentType.TEXT,
                file_hash=file_hash,
                section=section,
                section_level=section_level,
                chunk_index=start_index + len(chunks),
            )
            metadata.tags = self._extract_tags(chunk_content)
            
            chunks.append(DocumentChunk(
                content=chunk_content,
                metadata=metadata
            ))
        
        return chunks
    
    def _get_overlap(self, paragraphs: List[str]) -> str:
        """获取重叠文本（最后部分，约 80 字符）"""
        overlap_size = self.CHUNK_OVERLAP
        overlap_parts = []
        total = 0
        
        for para in reversed(paragraphs):
            if total + len(para) > overlap_size:
                break
            overlap_parts.insert(0, para)
            total += len(para)
        
        return '\n\n'.join(overlap_parts)
    
    def _extract_tags(self, content: str) -> List[str]:
        """从内容提取关键词标签"""
        tags = []
        content_lower = content.lower()
        
        # 技术关键词映射
        keyword_map = {
            "温度": ["温度", "temperature", "thermal"],
            "湿度": ["湿度", "humidity"],
            "压力": ["压力", "pressure"],
            "加速度": ["加速度", "accelerometer", "accel"],
            "陀螺仪": ["陀螺仪", "gyroscope", "gyro"],
            "磁力计": ["磁力计", "magnetometer", "mag"],
            "I2C": ["i2c", "iic"],
            "SPI": ["spi"],
            "UART": ["uart", "serial"],
            "GPIO": ["gpio"],
            "中断": ["中断", "interrupt"],
            "寄存器": ["寄存器", "register"],
            "校准": ["校准", "calibration", "calibrate"],
            "滤波": ["滤波", "filter"],
            "功耗": ["功耗", "power", "current", "consumption"],
        }
        
        for tag, keywords in keyword_map.items():
            if any(kw in content_lower for kw in keywords):
                tags.append(tag)
        
        return tags[:5]  # 最多 5 个标签


class PDFParser(BaseParser):
    """PDF 文档解析器"""
    
    CHUNK_SIZE = 500
    CHUNK_OVERLAP = 80
    
    def supports(self, file_path: Path) -> bool:
        return file_path.suffix.lower() == '.pdf'
    
    def parse(self, file_path: Path, doc_type: DocType) -> Document:
        """解析 PDF 为 Chunks"""
        try:
            import fitz
        except ImportError:
            raise RuntimeError("PyMuPDF (fitz) 未安装: pip install pymupdf")
        
        # 计算文件 hash（用于增量检测）
        file_stat = file_path.stat()
        file_hash = hashlib.md5(
            f"{file_stat.st_size}_{file_stat.st_mtime}".encode()
        ).hexdigest()
        
        # 创建 Document
        doc = Document(
            source=file_path,
            doc_type=doc_type,
            file_hash=file_hash
        )
        
        # 提取文本（按页）
        pages = []
        with fitz.open(file_path) as pdf:
            for page_num in range(len(pdf)):
                page = pdf[page_num]
                text = page.get_text()
                pages.append({
                    "page_num": page_num + 1,
                    "text": self._clean_text(text)
                })
        
        # 解析章节结构并分块
        doc.chunks = self._parse_structure(pages, file_path, doc_type, file_hash)
        
        # 更新 metadata
        for i, chunk in enumerate(doc.chunks):
            chunk.metadata.total_chunks = len(doc.chunks)
            chunk.metadata.chunk_index = i
        
        # 设置文档级 metadata
        if doc.chunks:
            doc.vendor = doc.chunks[0].metadata.vendor
            doc.chip = doc.chunks[0].metadata.chip
        
        logger.info(f"📖 PDF: {file_path.name} → {len(doc.chunks)} chunks")
        return doc
    
    def _clean_text(self, text: str) -> str:
        """清理 PDF 文本"""
        # 移除页眉页脚模式
        patterns = [
            r'BST-\w+-DS\d+-\d+.*?Revision.*\d+\.\d+',
            r'Page\s+\d+\s+of\s+\d+',
            r'©\s*Bosch Sensortec.*?reserved',
            r'BOSCH and the symbol are registered trademarks',
        ]
        for pattern in patterns:
            text = re.sub(pattern, '', text, flags=re.IGNORECASE)
        
        # 清理多余空白
        text = re.sub(r'\n{3,}', '\n\n', text)
        text = re.sub(r'[ \t]+', ' ', text)
        
        return text.strip()
    
    def _parse_structure(
        self,
        pages: List[Dict],
        file_path: Path,
        doc_type: DocType,
        file_hash: str
    ) -> List[DocumentChunk]:
        """
        解析 PDF 结构并分块
        
        策略：
        1. 按页处理，检测章节标题（大字体/粗体）
        2. 表格/寄存器表单独识别
        3. 按 chunk_size 切分，保留章节上下文
        """
        chunks = []
        current_section = "General"
        section_level = 0
        
        # 从文件名提取 vendor/chip
        vendor, chip = self._extract_vendor_chip(file_path)
        
        for page in pages:
            page_num = page["page_num"]
            text = page["text"]
            
            if not text:
                continue
            
            # 检测章节标题（简单启发式：短行、大写、数字开头）
            lines = text.split('\n')
            page_content = []
            
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                
                # 检测标题模式
                # 模式1: "1. Title" 或 "1.1 Subtitle"
                # 模式2: "Title" （短行，全部大写或首字母大写）
                if self._is_section_title(line):
                    # 先保存之前的内容
                    if page_content:
                        chunk_content = '\n'.join(page_content)
                        new_chunks = self._create_chunks_from_text(
                            chunk_content, current_section, section_level,
                            file_path, doc_type, file_hash, vendor, chip,
                            page_num, len(chunks)
                        )
                        chunks.extend(new_chunks)
                        page_content = []
                    
                    # 更新章节
                    current_section = line
                    section_level = self._get_section_level(line)
                else:
                    page_content.append(line)
            
            # 保存页面剩余内容
            if page_content:
                chunk_content = '\n'.join(page_content)
                new_chunks = self._create_chunks_from_text(
                    chunk_content, current_section, section_level,
                    file_path, doc_type, file_hash, vendor, chip,
                    page_num, len(chunks)
                )
                chunks.extend(new_chunks)
        
        return chunks
    
    def _is_section_title(self, line: str) -> bool:
        """检测是否为章节标题"""
        # 模式1: 数字编号 "1. Title" "1.1 Title" "1.1.1 Title"
        if re.match(r'^\d+(\.\d+)*\s+\w', line):
            return True
        
        # 模式2: 短行（< 60字符），且大部分是大写或首字母大写
        if len(line) < 60 and len(line) > 3:
            words = line.split()
            if len(words) <= 10:  # 不超过10个词
                upper_count = sum(1 for c in line if c.isupper())
                if upper_count > len(line) * 0.3:  # 30%以上大写
                    return True
        
        return False
    
    def _get_section_level(self, title: str) -> int:
        """获取章节级别"""
        match = re.match(r'^(\d+)(?:\.(\d+))?(?:\.(\d+))?', title)
        if match:
            parts = [p for p in match.groups() if p is not None]
            return len(parts)
        return 1
    
    def _extract_vendor_chip(self, file_path: Path) -> tuple:
        """从文件名提取 vendor 和 chip"""
        import re
        name = file_path.stem.lower()
        parts = name.replace('_datasheet', '').replace('-datasheet', '').split('_')
        
        if len(parts) >= 2:
            vendor = parts[0]
            chip = '_'.join(parts[1:])
            chip = re.sub(r'_(v?\d+\.?\d*|rev\d+|r\d+)$', '', chip, flags=re.I)
        else:
            vendor = "unknown"
            chip = parts[0] if parts else "unknown"
        
        return vendor, chip
    
    def _create_chunks_from_text(
        self,
        text: str,
        section: str,
        section_level: int,
        file_path: Path,
        doc_type: DocType,
        file_hash: str,
        vendor: str,
        chip: str,
        page: int,
        start_index: int
    ) -> List[DocumentChunk]:
        """从文本创建 chunks"""
        chunks = []
        
        # 检测内容类型
        content_type = self._detect_content_type(text)
        
        # 如果内容较短，直接作为一个 chunk
        if len(text) <= self.CHUNK_SIZE:
            metadata = ChunkMetadata(
                source=str(file_path),
                doc_type=doc_type.value,
                content_type=content_type,
                file_hash=file_hash,
                vendor=vendor,
                chip=chip,
                page=page,
                section=section,
                section_level=section_level,
                chunk_index=start_index,
            )
            metadata.tags = self._extract_tags(text, content_type)
            
            chunks.append(DocumentChunk(content=text, metadata=metadata))
            return chunks
        
        # 长内容切分（按段落）
        paragraphs = text.split('\n')
        current_chunk = []
        current_size = 0
        
        for para in paragraphs:
            para = para.strip()
            if not para:
                continue
            
            if current_size + len(para) > self.CHUNK_SIZE and current_chunk:
                chunk_content = '\n'.join(current_chunk)
                metadata = ChunkMetadata(
                    source=str(file_path),
                    doc_type=doc_type.value,
                    content_type=content_type,
                    file_hash=file_hash,
                    vendor=vendor,
                    chip=chip,
                    page=page,
                    section=section,
                    section_level=section_level,
                    chunk_index=start_index + len(chunks),
                )
                metadata.tags = self._extract_tags(chunk_content, content_type)
                
                chunks.append(DocumentChunk(content=chunk_content, metadata=metadata))
                
                # 重叠
                overlap = self._get_overlap(current_chunk)
                current_chunk = [overlap, para] if overlap else [para]
                current_size = sum(len(p) for p in current_chunk)
            else:
                current_chunk.append(para)
                current_size += len(para)
        
        # 最后一个 chunk
        if current_chunk:
            chunk_content = '\n'.join(current_chunk)
            metadata = ChunkMetadata(
                source=str(file_path),
                doc_type=doc_type.value,
                content_type=content_type,
                file_hash=file_hash,
                vendor=vendor,
                chip=chip,
                page=page,
                section=section,
                section_level=section_level,
                chunk_index=start_index + len(chunks),
            )
            metadata.tags = self._extract_tags(chunk_content, content_type)
            
            chunks.append(DocumentChunk(content=chunk_content, metadata=metadata))
        
        return chunks
    
    def _detect_content_type(self, text: str) -> str:
        """检测内容类型"""
        # 检测表格
        if '|' in text and text.count('\n') >= 2:
            lines = text.split('\n')
            if sum(1 for line in lines if '|' in line) >= 2:
                return ContentType.TABLE
        
        # 检测寄存器表
        if re.search(r'(?:bit|bits?)\s*\d+', text, re.I) and \
           re.search(r'(?:register|reg|address)', text, re.I):
            return ContentType.REGISTER
        
        # 检测代码
        if '```' in text or text.count(';') > 5:
            return ContentType.CODE
        
        return ContentType.TEXT
    
    def _get_overlap(self, paragraphs: List[str]) -> str:
        """获取重叠文本"""
        overlap_size = self.CHUNK_OVERLAP
        overlap_parts = []
        total = 0
        
        for para in reversed(paragraphs):
            if total + len(para) > overlap_size:
                break
            overlap_parts.insert(0, para)
            total += len(para)
        
        return '\n'.join(overlap_parts)
    
    def _extract_tags(self, content: str, content_type: str) -> List[str]:
        """提取标签"""
        tags = [content_type]  # 包含内容类型标签
        content_lower = content.lower()
        
        keyword_map = {
            "温度": ["温度", "temperature", "thermal"],
            "湿度": ["湿度", "humidity"],
            "压力": ["压力", "pressure"],
            "加速度": ["加速度", "accelerometer", "accel"],
            "陀螺仪": ["陀螺仪", "gyroscope", "gyro"],
            "磁力计": ["磁力计", "magnetometer", "mag"],
            "I2C": ["i2c", "iic"],
            "SPI": ["spi"],
            "UART": ["uart", "serial"],
            "GPIO": ["gpio"],
            "中断": ["中断", "interrupt"],
            "寄存器": ["寄存器", "register"],
            "校准": ["校准", "calibration"],
            "功耗": ["功耗", "power", "consumption"],
            "时序": ["时序", "timing", "sequence"],
            "电气": ["电气", "electrical", "voltage", "current"],
        }
        
        for tag, keywords in keyword_map.items():
            if any(kw in content_lower for kw in keywords):
                tags.append(tag)
        
        return tags[:6]


class DocumentProcessor:
    """
    统一文档处理器
    
    所有文档类型的统一入口
    """
    
    def __init__(self):
        self.parsers: List[BaseParser] = [
            MarkdownParser(),
            PDFParser(),
        ]
    
    def process(self, file_path: Path, doc_type: DocType = None) -> Document:
        """
        处理任意文档
        
        Args:
            file_path: 文件路径
            doc_type: 文档类型（可选，自动检测）
            
        Returns:
            Document 对象
        """
        file_path = Path(file_path)
        
        if not file_path.exists():
            raise FileNotFoundError(f"文件不存在: {file_path}")
        
        # 自动检测 doc_type
        if doc_type is None:
            doc_type = self._detect_doc_type(file_path)
        
        # 找到合适的 parser
        for parser in self.parsers:
            if parser.supports(file_path):
                return parser.parse(file_path, doc_type)
        
        raise ValueError(f"不支持的文件格式: {file_path.suffix}")
    
    def _detect_doc_type(self, file_path: Path) -> DocType:
        """根据文件路径自动检测文档类型"""
        path_lower = str(file_path).lower()
        
        # 关键词匹配
        if any(k in path_lower for k in ['chip', 'datasheet', 'sensor', 'mcu', 'cpu', 'ic']):
            return DocType.CHIP
        elif any(k in path_lower for k in ['practice', 'best', 'guide', 'tutorial', 'howto']):
            return DocType.PRACTICE
        elif any(k in path_lower for k in ['api', 'reference', 'doc']):
            return DocType.GUIDE
        
        # 默认根据扩展名
        if file_path.suffix.lower() == '.pdf':
            return DocType.CHIP
        
        return DocType.PRACTICE


# 便捷函数
def process_document(file_path: str | Path, doc_type: str = None) -> Document:
    """
    处理文档的便捷函数
    
    Args:
        file_path: 文件路径
        doc_type: 文档类型（chip/practice/guide）
        
    Returns:
        Document 对象
    """
    processor = DocumentProcessor()
    
    if doc_type:
        doc_type_enum = DocType(doc_type)
    else:
        doc_type_enum = None
    
    return processor.process(Path(file_path), doc_type_enum)
