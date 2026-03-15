"""
KB Integrator
Integrates knowledge base results with issue context
"""

import os
import logging
from typing import Optional, Dict, Any

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import IssueContext, KBResult
from .kb_client import KBClient

logger = logging.getLogger(__name__)


class KBIntegrator:
    """
    Integrates Knowledge Base with issue processing
    
    - Queries KB based on issue content
    - Enriches context with relevant knowledge
    - Provides knowledge-based suggestions
    """
    
    def __init__(
        self,
        kb_client: Optional[KBClient] = None,
        similarity_threshold: float = None
    ):
        self.client = kb_client or KBClient()
        self.similarity_threshold = similarity_threshold or float(
            os.environ.get("KB_SIMILARITY_THRESHOLD", "0.7")
        )
        self.enabled = os.environ.get(
            "KB_SERVICE_ENABLED", "true"
        ).lower() == "true"
    
    def enrich_context(
        self,
        context: IssueContext,
        query_text: str = None
    ) -> str:
        """
        Enrich issue context with knowledge base results
        
        Args:
            context: Issue context
            query_text: Optional specific query text (defaults to issue content)
            
        Returns:
            Enriched context string
        """
        if not self.enabled:
            logger.debug("KB Service disabled, skipping enrichment")
            return context.build_full_context()
        
        if not self.client.health_check():
            logger.warning("KB Service not available, skipping enrichment")
            return context.build_full_context()
        
        # Build query from issue content
        if query_text is None:
            query_text = f"{context.title}\n{context.body}"
        
        # Query knowledge base
        kb_result = self.client.query(
            query_text=query_text,
            top_k=3,
            generate_answer=True
        )
        
        if not kb_result:
            logger.debug("No KB results found")
            return context.build_full_context()
        
        # Check similarity threshold
        results = kb_result.get('results', [])
        if not results:
            logger.debug("KB returned empty results")
            return context.build_full_context()
        
        best_similarity = results[0].get('similarity', 0)
        if best_similarity < self.similarity_threshold:
            logger.debug(
                f"Best KB match similarity {best_similarity:.2f} below threshold "
                f"{self.similarity_threshold}"
            )
            return context.build_full_context()
        
        logger.info(
            f"KB enrichment: best match {best_similarity:.2f} similarity, "
            f"{len(results)} results"
        )
        
        # Build enriched context
        base_context = context.build_full_context()
        kb_context = self.client.format_results_for_context(kb_result)
        
        enriched = f"""{base_context}

{kb_context}

=== 使用知识库 ===
基于知识库文档回答用户问题或指导代码修改。
"""
        return enriched
    
    def get_solution_suggestion(
        self,
        query_text: str
    ) -> Optional[Dict[str, Any]]:
        """
        Get solution suggestion from knowledge base
        
        Args:
            query_text: Problem description
            
        Returns:
            Suggestion with solution and references
        """
        if not self.enabled or not self.client.health_check():
            return None
        
        kb_result = self.client.query(
            query_text=query_text,
            top_k=3,
            generate_answer=True
        )
        
        if not kb_result:
            return None
        
        results = kb_result.get('results', [])
        if not results or results[0].get('similarity', 0) < self.similarity_threshold:
            return None
        
        return {
            "answer": kb_result.get('answer', ''),
            "source": results[0].get('source_file', ''),
            "similarity": results[0].get('similarity', 0),
            "all_sources": [r.get('source_file') for r in results]
        }
    
    def check_common_issues(
        self,
        issue_title: str,
        issue_body: str
    ) -> Optional[str]:
        """
        Check if this is a known/common issue with documented solution
        
        Args:
            issue_title: Issue title
            issue_body: Issue body
            
        Returns:
            Pre-written response if known issue found
        """
        query = f"{issue_title}\n{issue_body}"
        suggestion = self.get_solution_suggestion(query)
        
        if not suggestion:
            return None
        
        # Format response for known issue
        response = f"""🤖 [知识库匹配]

{suggestion['answer']}

---
📚 **参考文档**: {suggestion['source']}
🎯 **匹配度**: {suggestion['similarity']:.1%}

*此回答基于知识库文档自动生成。如果未能解决您的问题，请提供更多细节。*"""
        
        return response
    
    def get_hardware_reference(
        self,
        chip_name: str,
        topic: str
    ) -> Optional[str]:
        """
        Get hardware-specific reference (e.g., chip datasheet info)
        
        Args:
            chip_name: Chip name (e.g., "SD3031", "DS3231")
            topic: Topic to query (e.g., "1Hz output", "INT pin configuration")
            
        Returns:
            Reference information from knowledge base
        """
        query = f"{chip_name} {topic}"
        
        kb_result = self.client.query(
            query_text=query,
            top_k=2,
            generate_answer=False  # Just get raw documents
        )
        
        if not kb_result or not kb_result.get('results'):
            return None
        
        results = kb_result.get('results', [])
        if not results:
            return None
        
        # Format hardware reference
        ref_parts = [f"=== {chip_name} 技术参考 ===\n"]
        
        for result in results:
            content = result.get('content', '')
            source = result.get('source_file', '')
            
            ref_parts.append(f"\n【来源: {source}】\n")
            ref_parts.append(content)
        
        return "\n".join(ref_parts)
