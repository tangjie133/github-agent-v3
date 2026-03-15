"""
Local Knowledge Base Manager
Manages local knowledge documents and indexing
"""

import os
import json
import logging
from pathlib import Path
from typing import List, Dict, Any, Optional
from datetime import datetime

logger = logging.getLogger(__name__)


class LocalKBManager:
    """
    Manages local knowledge base documents
    
    - Document organization
    - Metadata tracking
    - Index status management
    """
    
    def __init__(self, kb_dir: str = None):
        self.kb_dir = Path(kb_dir or "./knowledge_base")
        self.kb_dir.mkdir(parents=True, exist_ok=True)
        
        # Subdirectories (保留兼容性，但不再自动创建)
        # 注意：新版架构中知识库文件直接存入 ChromaDB，不再保存到本地目录
        self.chips_dir = self.kb_dir / "chips"
        self.best_practices_dir = self.kb_dir / "best_practices"
        self.history_dir = self.kb_dir / "history"
        
        # Metadata file
        self.metadata_file = self.kb_dir / "metadata.json"
        self.metadata = self._load_metadata()
    
    def _load_metadata(self) -> Dict[str, Any]:
        """Load metadata from file"""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, 'r') as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Failed to load metadata: {e}")
        
        return {
            "version": "1.0",
            "last_sync": None,
            "documents": {},
            "indexed": []
        }
    
    def _save_metadata(self):
        """Save metadata to file"""
        try:
            with open(self.metadata_file, 'w') as f:
                json.dump(self.metadata, f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save metadata: {e}")
    
    def add_chip_document(
        self,
        chip_name: str,
        content: str,
        source: str = "manual"
    ) -> Path:
        """
        Add chip-specific documentation
        
        Args:
            chip_name: Chip name (e.g., "SD3031")
            content: Document content
            source: Document source
            
        Returns:
            Path to created file
        """
        # Create chip directory
        chip_dir = self.chips_dir / chip_name.lower()
        chip_dir.mkdir(exist_ok=True)
        
        # Save document
        doc_file = chip_dir / f"{chip_name.lower()}.md"
        
        # Add frontmatter
        doc_content = f"""---
title: {chip_name} Technical Documentation
category: chip
source: {source}
date: {datetime.now().isoformat()}
---

# {chip_name}

{content}
"""
        
        with open(doc_file, 'w') as f:
            f.write(doc_content)
        
        # Update metadata
        self.metadata["documents"][str(doc_file)] = {
            "type": "chip",
            "name": chip_name,
            "added": datetime.now().isoformat(),
            "indexed": False
        }
        self._save_metadata()
        
        logger.info(f"Added chip document: {doc_file}")
        return doc_file
    
    def add_best_practice(
        self,
        title: str,
        content: str,
        tags: List[str] = None
    ) -> Path:
        """
        Add best practice document
        
        Args:
            title: Document title
            content: Document content
            tags: List of tags
            
        Returns:
            Path to created file
        """
        # Generate filename
        filename = title.lower().replace(" ", "_").replace("/", "_") + ".md"
        doc_file = self.best_practices_dir / filename
        
        # Add frontmatter
        tags_str = ", ".join(tags) if tags else ""
        doc_content = f"""---
title: {title}
category: best_practice
tags: [{tags_str}]
date: {datetime.now().isoformat()}
---

# {title}

{content}
"""
        
        with open(doc_file, 'w') as f:
            f.write(doc_content)
        
        # Update metadata
        self.metadata["documents"][str(doc_file)] = {
            "type": "best_practice",
            "title": title,
            "tags": tags or [],
            "added": datetime.now().isoformat(),
            "indexed": False
        }
        self._save_metadata()
        
        logger.info(f"Added best practice: {doc_file}")
        return doc_file
    
    def add_history_record(
        self,
        repo: str,
        issue_number: int,
        fix_description: str,
        files_modified: List[str]
    ) -> Path:
        """
        Add fix history record for learning
        
        Args:
            repo: Repository name
            issue_number: Issue number
            fix_description: Description of the fix
            files_modified: List of modified files
            
        Returns:
            Path to created file
        """
        # Create repo directory
        repo_dir = self.history_dir / repo.replace("/", "-")
        repo_dir.mkdir(exist_ok=True)
        
        # Save record
        filename = f"fix-issue-{issue_number}.md"
        doc_file = repo_dir / filename
        
        files_list = "\n".join([f"- {f}" for f in files_modified])
        doc_content = f"""---
title: Fix for Issue #{issue_number}
repo: {repo}
issue_number: {issue_number}
category: history
date: {datetime.now().isoformat()}
---

# Issue #{issue_number} Fix

## Description

{fix_description}

## Files Modified

{files_list}

## Lessons Learned

<!-- Add insights for future reference -->
"""
        
        with open(doc_file, 'w') as f:
            f.write(doc_content)
        
        logger.info(f"Added history record: {doc_file}")
        return doc_file
    
    def list_documents(self, doc_type: str = None) -> List[Dict[str, Any]]:
        """
        List all documents in knowledge base
        
        Args:
            doc_type: Filter by type (chip, best_practice, history)
            
        Returns:
            List of document info
        """
        docs = []
        
        for path_str, info in self.metadata["documents"].items():
            if doc_type is None or info.get("type") == doc_type:
                docs.append({
                    "path": path_str,
                    **info
                })
        
        return docs
    
    def mark_indexed(self, doc_path: str):
        """Mark document as indexed"""
        if doc_path in self.metadata["documents"]:
            self.metadata["documents"][doc_path]["indexed"] = True
            self.metadata["documents"][doc_path]["indexed_at"] = datetime.now().isoformat()
            
            if doc_path not in self.metadata["indexed"]:
                self.metadata["indexed"].append(doc_path)
            
            self._save_metadata()
    
    def get_stats(self) -> Dict[str, Any]:
        """Get knowledge base statistics"""
        total = len(self.metadata["documents"])
        indexed = len(self.metadata["indexed"])
        
        by_type = {}
        for info in self.metadata["documents"].values():
            t = info.get("type", "unknown")
            by_type[t] = by_type.get(t, 0) + 1
        
        return {
            "total_documents": total,
            "indexed": indexed,
            "pending_index": total - indexed,
            "by_type": by_type,
            "kb_directory": str(self.kb_dir)
        }
    
    def find_chip_docs(self, chip_name: str) -> List[Path]:
        """Find all documents for a specific chip"""
        chip_dir = self.chips_dir / chip_name.lower()
        
        if not chip_dir.exists():
            return []
        
        return list(chip_dir.glob("*.md"))
