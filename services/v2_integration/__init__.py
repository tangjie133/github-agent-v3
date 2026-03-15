"""
V2 集成模块

将 V2 的可用组件集成到 V3 架构中
"""

from services.v2_integration.adapter import (
    V2CodeExecutorAdapter,
    V2IntentClassifierAdapter,
    V2KnowledgeBaseAdapter,
    get_v2_code_executor,
    get_v2_intent_classifier,
    get_v2_knowledge_base,
)

__all__ = [
    'V2CodeExecutorAdapter',
    'V2IntentClassifierAdapter', 
    'V2KnowledgeBaseAdapter',
    'get_v2_code_executor',
    'get_v2_intent_classifier',
    'get_v2_knowledge_base',
]