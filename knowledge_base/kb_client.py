"""
KB Service Client
Client for querying the local Knowledge Base Service
"""

import os
import requests
import logging
from typing import List, Dict, Any, Optional

logger = logging.getLogger(__name__)


class KBClient:
    """
    Client for Knowledge Base Service
    Provides RAG (Retrieval-Augmented Generation) capabilities
    """
    
    def __init__(self, base_url: str = None):
        self.base_url = base_url or os.environ.get(
            "KB_SERVICE_URL", "http://localhost:8000"
        )
        self.timeout = 30
    
    def health_check(self) -> bool:
        """Check if KB Service is available"""
        try:
            response = requests.get(
                f"{self.base_url}/health",
                timeout=5
            )
            return response.status_code == 200
        except Exception as e:
            logger.warning(f"KB Service health check failed: {e}")
            return False
    
    def query(
        self,
        query_text: str,
        top_k: int = 3,
        generate_answer: bool = True
    ) -> Optional[Dict[str, Any]]:
        """
        Query knowledge base
        
        Args:
            query_text: Query text
            top_k: Number of top results to return
            generate_answer: Whether to generate AI answer
            
        Returns:
            Query result with documents and optional answer
        """
        try:
            logger.info(f"Querying KB: {query_text[:50]}...")
            
            response = requests.post(
                f"{self.base_url}/query",
                json={
                    "query": query_text,
                    "top_k": top_k,
                    "generate_answer": generate_answer
                },
                timeout=self.timeout
            )
            response.raise_for_status()
            
            result = response.json()
            logger.info(f"KB query returned {len(result.get('results', []))} results")
            return result
            
        except requests.exceptions.ConnectionError:
            logger.error("KB Service connection failed")
            return None
        except requests.exceptions.Timeout:
            logger.error("KB Service timeout")
            return None
        except Exception as e:
            logger.error(f"KB query failed: {e}")
            return None
    
    def query_sync(
        self,
        query_text: str,
        top_k: int = 3,
        generate_answer: bool = True
    ) -> Optional[Dict[str, Any]]:
        """Synchronous query (alias for query)"""
        return self.query(query_text, top_k, generate_answer)
    
    def get_stats(self) -> Optional[Dict[str, Any]]:
        """Get KB Service statistics"""
        try:
            response = requests.get(
                f"{self.base_url}/stats",
                timeout=5
            )
            response.raise_for_status()
            return response.json()
        except Exception as e:
            logger.warning(f"Failed to get KB stats: {e}")
            return None
    
    def sync(self) -> bool:
        """Trigger manual sync of knowledge base"""
        try:
            logger.info("Triggering KB sync...")
            response = requests.post(
                f"{self.base_url}/sync",
                timeout=60
            )
            response.raise_for_status()
            logger.info("KB sync completed")
            return True
        except Exception as e:
            logger.error(f"KB sync failed: {e}")
            return False
    
    def format_results_for_context(
        self,
        kb_result: Dict[str, Any],
        max_length: int = 2000
    ) -> str:
        """
        Format KB results for inclusion in AI context
        
        Args:
            kb_result: KB query result
            max_length: Maximum length of formatted text
            
        Returns:
            Formatted context string
        """
        if not kb_result or not kb_result.get('results'):
            return ""
        
        parts = []
        parts.append("=== 知识库参考 ===\n")
        
        # Add generated answer if available
        answer = kb_result.get('answer', '')
        if answer:
            parts.append(f"【综合分析】\n{answer}\n")
        
        # Add top matching documents
        results = kb_result.get('results', [])
        if results:
            parts.append("【相关文档】\n")
            for i, result in enumerate(results[:3], 1):
                content = result.get('content', '')[:500]  # Limit content length
                source = result.get('source_file', 'Unknown')
                similarity = result.get('similarity', 0)
                
                parts.append(f"\n[{i}] {source} (匹配度: {similarity:.1%})\n")
                parts.append(f"{content}\n")
        
        context = "\n".join(parts)
        
        # Truncate if too long
        if len(context) > max_length:
            context = context[:max_length] + "\n... [内容已截断]"
        
        return context
