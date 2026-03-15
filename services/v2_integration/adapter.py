"""
V2 → V3 适配器

将 V2 的同步代码包装为异步接口，供 V3 的 Worker 调用
"""

import asyncio
import sys
import os
from typing import Dict, Any, Optional
from pathlib import Path

# 添加 V2 组件路径
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "core" / "v2_adapters"))

from core.logging import get_logger
from core.config import get_config

logger = get_logger(__name__)


class V2CodeExecutorAdapter:
    """
    V2 Code Executor 适配器
    
    包装 V2 的代码分析、生成、执行功能
    """
    
    def __init__(self):
        self.config = get_config()
        self._executor = None
        self._analyzer = None
        self._generator = None
    
    def _get_executor(self):
        """懒加载 V2 CodeExecutor"""
        if self._executor is None:
            from code_executor.code_executor import CodeExecutor
            from cloud_agent.openclaw_client import OpenClawClient
            
            openclaw = OpenClawClient(
                api_key=os.getenv("OPENCLAW_API_KEY", ""),
                base_url=self.config.llm.openclaw_url
            )
            self._executor = CodeExecutor(openclaw_client=openclaw)
        return self._executor
    
    def _get_analyzer(self):
        """懒加载 V2 CodeAnalyzer"""
        if self._analyzer is None:
            from code_executor.code_analyzer import CodeAnalyzer
            self._analyzer = CodeAnalyzer()
        return self._analyzer
    
    def _get_generator(self):
        """懒加载 V2 CodeGenerator"""
        if self._generator is None:
            from code_executor.code_generator import CodeGenerator
            from cloud_agent.openclaw_client import OpenClawClient
            
            openclaw = OpenClawClient(
                api_key=os.getenv("OPENCLAW_API_KEY", ""),
                base_url=self.config.llm.openclaw_url
            )
            self._generator = CodeGenerator(llm_client=openclaw)
        return self._generator
    
    async def analyze_issue(self, repo_path: str, issue_title: str, 
                           issue_body: str) -> Dict[str, Any]:
        """
        分析 Issue，识别需要修改的文件
        
        调用 V2 CodeAnalyzer 的同步代码，在线程池中执行
        """
        loop = asyncio.get_event_loop()
        analyzer = self._get_analyzer()
        
        try:
            # 在线程池中执行同步代码
            result = await loop.run_in_executor(
                None,  # 使用默认线程池
                lambda: analyzer.analyze_issue(
                    repo_path=repo_path,
                    issue_title=issue_title,
                    issue_body=issue_body
                )
            )
            return result
        except Exception as e:
            logger.error("v2_adapter.analyze_failed", error=str(e))
            raise
    
    async def generate_fix(self, repo_path: str, file_path: str,
                          issue_description: str) -> Dict[str, Any]:
        """
        生成代码修复
        """
        loop = asyncio.get_event_loop()
        generator = self._get_generator()
        
        try:
            result = await loop.run_in_executor(
                None,
                lambda: generator.generate_fix(
                    repo_path=repo_path,
                    file_path=file_path,
                    issue_description=issue_description
                )
            )
            return result
        except Exception as e:
            logger.error("v2_adapter.generate_failed", error=str(e))
            raise
    
    async def execute_fix(self, repo_path: str, changes: list) -> bool:
        """
        执行代码修改
        """
        loop = asyncio.get_event_loop()
        executor = self._get_executor()
        
        try:
            result = await loop.run_in_executor(
                None,
                lambda: executor.apply_changes(repo_path, changes)
            )
            return result
        except Exception as e:
            logger.error("v2_adapter.execute_failed", error=str(e))
            raise


class V2IntentClassifierAdapter:
    """
    V2 意图分类器适配器
    """
    
    def __init__(self):
        self._classifier = None
    
    def _get_classifier(self):
        if self._classifier is None:
            from cloud_agent.intent_classifier import IntentClassifier
            self._classifier = IntentClassifier()
        return self._classifier
    
    async def classify(self, text: str) -> Dict[str, Any]:
        """
        分类用户意图
        """
        loop = asyncio.get_event_loop()
        classifier = self._get_classifier()
        
        try:
            result = await loop.run_in_executor(
                None,
                lambda: classifier.classify(text)
            )
            return result
        except Exception as e:
            logger.error("v2_adapter.classify_failed", error=str(e))
            raise


class V2KnowledgeBaseAdapter:
    """
    V2 知识库适配器
    """
    
    def __init__(self):
        self._kb = None
    
    def _get_kb(self):
        if self._kb is None:
            from knowledge_base.kb_service import KnowledgeBaseService
            self._kb = KnowledgeBaseService()
        return self._kb
    
    async def query(self, query: str, repo: str = None) -> list:
        """
        查询知识库
        """
        loop = asyncio.get_event_loop()
        kb = self._get_kb()
        
        try:
            result = await loop.run_in_executor(
                None,
                lambda: kb.query(query, repo)
            )
            return result
        except Exception as e:
            logger.error("v2_adapter.kb_query_failed", error=str(e))
            return []


# 全局单例
_code_executor_adapter: Optional[V2CodeExecutorAdapter] = None
_intent_classifier_adapter: Optional[V2IntentClassifierAdapter] = None
_kb_adapter: Optional[V2KnowledgeBaseAdapter] = None


def get_v2_code_executor() -> V2CodeExecutorAdapter:
    """获取 V2 CodeExecutor 适配器"""
    global _code_executor_adapter
    if _code_executor_adapter is None:
        _code_executor_adapter = V2CodeExecutorAdapter()
    return _code_executor_adapter


def get_v2_intent_classifier() -> V2IntentClassifierAdapter:
    """获取 V2 意图分类器适配器"""
    global _intent_classifier_adapter
    if _intent_classifier_adapter is None:
        _intent_classifier_adapter = V2IntentClassifierAdapter()
    return _intent_classifier_adapter


def get_v2_knowledge_base() -> V2KnowledgeBaseAdapter:
    """获取 V2 知识库适配器"""
    global _kb_adapter
    if _kb_adapter is None:
        _kb_adapter = V2KnowledgeBaseAdapter()
    return _kb_adapter