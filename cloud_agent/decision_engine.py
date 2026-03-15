"""
Decision Engine
Makes decisions based on intent and creates action plans
"""

import logging
from typing import Dict, Any, List, Optional
from dataclasses import dataclass, field

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import IntentResult, IntentType

logger = logging.getLogger(__name__)


@dataclass
class ActionPlan:
    """Action plan for handling an issue"""
    action: str  # reply, modify, research, skip
    complexity: str  # simple, medium, complex
    files_to_modify: List[str] = field(default_factory=list)
    change_description: str = ""
    response: str = ""  # For non-modify actions
    confidence: float = 0.5
    needs_confirmation: bool = False
    research_topics: List[str] = field(default_factory=list)


class DecisionEngine:
    """
    Makes decisions on how to handle issues based on intent
    
    Decides:
    - Whether to create PR or just reply
    - Complexity of the change
    - Files to modify
    - Whether to wait for user confirmation
    """
    
    def __init__(self, openclaw_client=None):
        self.client = openclaw_client
    
    def make_decision(
        self,
        context_text: str,
        intent_result: IntentResult
    ) -> ActionPlan:
        """
        Make decision based on intent
        
        Args:
            context_text: Full issue context
            intent_result: Classified intent
            
        Returns:
            Action plan
        """
        intent = intent_result.intent
        
        logger.info(f"🎯 [Decision Engine] Making decision for intent: {intent.value}")
        logger.info(f"   OpenClaw client available: {self.client is not None}")
        
        if intent == IntentType.ANSWER:
            return self._handle_answer(context_text, intent_result)
        elif intent == IntentType.MODIFY:
            return self._handle_modify(context_text, intent_result)
        elif intent == IntentType.RESEARCH:
            return self._handle_research(context_text, intent_result)
        elif intent == IntentType.CLARIFY:
            return self._handle_clarify(context_text, intent_result)
        else:
            return ActionPlan(
                action="skip",
                complexity="simple",
                response="Unknown intent, skipping"
            )
    
    def _handle_answer(
        self,
        context_text: str,
        intent_result: IntentResult
    ) -> ActionPlan:
        """Handle answer intent - provide explanation"""
        logger.info("Decision: provide answer/explanation")
        
        # Check if this is about previous modification
        is_about_previous = any(
            keyword in context_text.lower()
            for keyword in ["修改", "pr", "pull request", "依据", "为什么"]
        )
        
        if is_about_previous:
            response = (
                "🤖 关于之前的修改：\n\n"
                "我之前提交的修改是基于对问题的分析。\n\n"
                "如果您认为修改不合理，请告诉我：\n"
                "1. 具体问题是什么\n"
                "2. 期望的修改方式\n\n"
                "我会根据您的反馈重新调整。"
            )
        else:
            response = (
                "🤖 感谢您的提问！\n\n"
                "我会查看相关资料后给您回复。"
            )
        
        return ActionPlan(
            action="reply",
            complexity="simple",
            response=response,
            confidence=intent_result.confidence
        )
    
    def _handle_modify(
        self,
        context_text: str,
        intent_result: IntentResult
    ) -> ActionPlan:
        """Handle modify intent - plan code changes"""
        logger.info("📝 [Decision Engine] Decision: plan code modification")
        
        # Use OpenClaw for detailed planning if available
        if self.client:
            try:
                logger.info("🔄 [Decision Engine] Trying OpenClaw for detailed planning...")
                decision = self.client.make_decision(
                    context_text,
                    intent_result.intent.value
                )
                logger.info("✅ [Decision Engine] OpenClaw planning successful")
                
                return ActionPlan(
                    action="modify",
                    complexity=decision.get("complexity", "simple"),
                    files_to_modify=decision.get("files_to_modify", []),
                    change_description=decision.get("change_description", ""),
                    confidence=decision.get("confidence", 0.5),
                    needs_confirmation=False
                )
            except Exception as e:
                logger.warning(f"⚠️  [Decision Engine] OpenClaw planning failed: {e}")
                logger.info("🔄 [Decision Engine] Using LOCAL FALLBACK for modification plan")
        else:
            logger.info("🔄 [Decision Engine] OpenClaw not available, using LOCAL FALLBACK")
        
        # Fallback: simple modification plan
        return ActionPlan(
            action="modify",
            complexity="simple",
            files_to_modify=[],
            change_description="Code modification based on issue description",
            confidence=intent_result.confidence,
            needs_confirmation=False
        )
    
    def _handle_research(
        self,
        context_text: str,
        intent_result: IntentResult
    ) -> ActionPlan:
        """Handle research intent - query knowledge base"""
        logger.info("Decision: research required")
        
        return ActionPlan(
            action="research",
            complexity="medium",
            research_topics=intent_result.research_topics,
            response=(
                "🤖 这个问题需要查询相关资料。\n\n"
                f"需要查询：{', '.join(intent_result.research_topics)}\n\n"
                "请稍候，或提供更多具体信息。"
            ),
            confidence=intent_result.confidence
        )
    
    def _handle_clarify(
        self,
        context_text: str,
        intent_result: IntentResult
    ) -> ActionPlan:
        """Handle clarify intent - request more info"""
        logger.info("Decision: request clarification")
        
        return ActionPlan(
            action="reply",
            complexity="simple",
            response="""🤖 我需要更多信息来帮助您。

请提供：
1. 具体的错误信息或现象
2. 相关的代码片段或文件路径
3. 期望的行为和实际的行为

有了这些信息后，我可以更准确地分析和修复问题。""",
            confidence=intent_result.confidence
        )
    
    def should_auto_execute(self, plan: ActionPlan) -> bool:
        """
        Determine if action should be executed automatically
        or wait for user confirmation
        
        Args:
            plan: Action plan
            
        Returns:
            True if should auto-execute
        """
        # Check confidence threshold
        if plan.confidence < 0.6:
            logger.info("Low confidence, suggesting manual confirmation")
            return False
        
        # Check complexity
        if plan.complexity == "complex":
            logger.info("Complex change, suggesting manual confirmation")
            return False
        
        return True
