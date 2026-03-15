"""
Intent Classifier
Uses OpenClaw AI to classify user intent from issue/comment context
"""

import logging
from typing import Optional

import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from core.models import IssueContext, IntentResult, IntentType
from .openclaw_client import OpenClawClient

logger = logging.getLogger(__name__)


class IntentClassifier:
    """
    Classifies user intent using OpenClaw AI
    
    Determines whether user wants:
    - answer: explanation, discussion
    - modify: code changes
    - research: needs investigation
    - clarify: insufficient information
    """
    
    # 本地规则关键词（用于 OpenClaw 失败时的备用）
    RESEARCH_KEYWORDS = [
        "查询", "查一下", "查查", "搜索", "找一下", "资料",
        "手册", "规格", "参数", "datasheet", "数据手册"
    ]
    
    ANSWER_KEYWORDS = [
        "为什么", "怎么回事", "原因", "解释", "说明", 
        "是什么", "什么是", "介绍一下", "讲讲"
    ]
    
    MODIFY_KEYWORDS = [
        "修复", "修改", "改成", "改为", "修复", "改一下",
        "fix", "change", "update", "repair", "correct",
        "解决", "帮我解决", "处理", "搞定", "修一下",
        "solve", "resolve", "help me fix", "not working",
        "报错", "错误", "exception", "error", "bug"
    ]
    
    # 上下文线索 - 表明需要代码修改的场景
    CODE_CONTEXT_INDICATORS = [
        "can't seem to", "not working", "not correct", "incorrect",
        "代码", "程序", "函数", "class", "module",
        "运行", "执行", "编译", "调试"
    ]
    
    def __init__(self, openclaw_client: Optional[OpenClawClient] = None):
        self.client = openclaw_client or OpenClawClient()
    
    def classify(self, context: IssueContext) -> IntentResult:
        """
        Classify intent from issue context
        
        Uses OpenClaw AI first, falls back to local rule-based classification if OpenClaw fails.
        
        Args:
            context: Complete issue context
            
        Returns:
            Intent classification result
        """
        # Build full context text
        context_text = context.build_full_context()
        
        logger.info(f"🎯 [Intent Classification] Starting for issue #{context.issue_number}")
        logger.info(f"   Context preview: {context_text[:80]}...")
        
        # Call OpenClaw for intent classification
        try:
            result = self.client.classify_intent(context_text)
            
            # Map to IntentType
            intent_map = {
                "answer": IntentType.ANSWER,
                "modify": IntentType.MODIFY,
                "research": IntentType.RESEARCH,
                "clarify": IntentType.CLARIFY
            }
            
            intent_type = intent_map.get(
                result.get("intent", "clarify"),
                IntentType.CLARIFY
            )
            
            intent_result = IntentResult(
                intent=intent_type,
                confidence=result.get("confidence", 0.5),
                reasoning=result.get("reasoning", ""),
                needs_research=result.get("needs_research", False),
                research_topics=result.get("research_topics", [])
            )
            
            logger.info(
                f"✅ [Intent Classification] SUCCESS via OpenClaw: "
                f"{intent_result.intent.value} (confidence: {intent_result.confidence:.2f})"
            )
            logger.info(f"   Reasoning: {intent_result.reasoning[:100]}...")
            
            return intent_result
            
        except Exception as e:
            logger.warning(f"⚠️  [Intent Classification] OpenClaw FAILED: {e}")
            logger.info(f"🔄 [Intent Classification] Switching to LOCAL RULES fallback")
            # Use local rule-based classification as fallback
            result = self._classify_with_rules(context_text)
            logger.info(
                f"✅ [Intent Classification] SUCCESS via LOCAL RULES: "
                f"{result.intent.value} (confidence: {result.confidence:.2f})"
            )
            logger.info(f"   Reasoning: {result.reasoning}")
            return result
    
    def _classify_with_rules(self, text: str) -> IntentResult:
        """
        Classify intent using local keyword rules (fallback when OpenClaw fails)
        
        This is a simple but fast classification method
        """
        text_lower = text.lower()
        
        logger.info(f"   [Local Rules] Analyzing text: {text[:60]}...")
        
        # Check for research keywords (highest priority for hardware questions)
        research_matches = [kw for kw in self.RESEARCH_KEYWORDS if kw in text_lower]
        if len(research_matches) >= 2:
            logger.info(f"   [Local Rules] ✅ MATCHED {len(research_matches)} research keywords: {research_matches[:3]}")
            return IntentResult(
                intent=IntentType.RESEARCH,
                confidence=0.7,
                reasoning=f"Local rule: Found {len(research_matches)} research-related keywords",
                needs_research=True,
                research_topics=["查询芯片手册获取技术参数"]
            )
        
        # Check for answer keywords
        answer_matches = [kw for kw in self.ANSWER_KEYWORDS if kw in text_lower]
        if answer_matches:
            logger.info(f"   [Local Rules] ✅ MATCHED {len(answer_matches)} answer keywords: {answer_matches}")
            return IntentResult(
                intent=IntentType.ANSWER,
                confidence=0.6,
                reasoning=f"Local rule: Found {len(answer_matches)} answer-related keywords",
                needs_research=False,
                research_topics=[]
            )
        
        # Check for modify keywords
        modify_matches = [kw for kw in self.MODIFY_KEYWORDS if kw in text_lower]
        if modify_matches:
            logger.info(f"   [Local Rules] ✅ MATCHED {len(modify_matches)} modify keywords: {modify_matches[:3]}")
            return IntentResult(
                intent=IntentType.MODIFY,
                confidence=0.6,
                reasoning=f"Local rule: Found {len(modify_matches)} modification keywords",
                needs_research=False,
                research_topics=[]
            )
        
        # Default to research for hardware-related questions
        chip_keywords = ["sd3031", "samd21", "芯片", "rtc", "mcu"]
        found_chips = [chip for chip in chip_keywords if chip in text_lower]
        if found_chips:
            logger.info(f"   [Local Rules] ✅ MATCHED hardware chips: {found_chips}")
            return IntentResult(
                intent=IntentType.RESEARCH,
                confidence=0.5,
                reasoning="Local rule: Hardware-related question, defaulting to research",
                needs_research=True,
                research_topics=["查询相关硬件资料"]
            )
        
        # Default fallback
        logger.info(f"   [Local Rules] ⚠️  No keywords matched, using default fallback")
        return IntentResult(
            intent=IntentType.ANSWER,
            confidence=0.5,
            reasoning="Local rule: No clear keywords found, defaulting to answer",
            needs_research=False,
            research_topics=[]
        )
    
    def classify_with_history(
        self,
        context: IssueContext,
        previous_intent: Optional[IntentType] = None,
        processing_count: int = 0
    ) -> IntentResult:
        """
        Classify intent with historical context
        
        This helps avoid duplicate processing and understand conversation flow
        
        Args:
            context: Current issue context
            previous_intent: Previous intent classification (if any)
            processing_count: How many times this issue has been processed
            
        Returns:
            Intent classification result
        """
        # Get base classification
        result = self.classify(context)
        
        # Adjust based on history
        if processing_count > 0:
            # Issue has been processed before
            logger.info(f"Issue has been processed {processing_count} times before")
            
            # If this looks like a duplicate modification request
            if result.intent == IntentType.MODIFY and processing_count >= 2:
                # Check if user is asking for modification again
                if "不对" in context.current_instruction or \
                   "重新" in context.current_instruction or \
                   "不行" in context.current_instruction:
                    logger.info("Detected modification retry")
                    # Keep modify intent but note it's a retry
                    result.reasoning += " (retry with modifications)"
                else:
                    # User might be asking about previous modification
                    logger.info("Possible question about previous modification")
                    # Don't change intent, but processor should handle accordingly
        
        return result
