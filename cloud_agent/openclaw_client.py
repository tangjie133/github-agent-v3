"""
OpenClaw Client for Cloud Agent
Wraps OpenClaw CLI for intent recognition and decision making
"""

import os
import json
import re
import subprocess
import logging
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class OpenClawClient:
    """
    Client for OpenClaw AI service
    Used for intent classification and decision making
    """
    
    def __init__(
        self,
        api_url: str = None,
        agent: str = "main",
        timeout: int = 120, #超时时间
        max_retries: int = 2 #重复次数
    ):
        self.api_url = api_url or os.environ.get(
            "OPENCLAW_API_URL", "http://localhost:3000/api/v1"
        )
        self.agent = agent
        self.timeout = timeout
        self.max_retries = max_retries
        
        # 清理可能存在的锁文件
        self._cleanup_lock_files()
    
    def classify_intent(self, context_text: str) -> Dict[str, Any]:
        """
        Classify user intent from issue/comment context
        
        Args:
            context_text: Full context (issue + comments)
            
        Returns:
            Intent classification result
        """
        prompt = self._build_intent_prompt(context_text)
        
        try:
            result = self._call_openclaw(prompt)
            return self._parse_intent_response(result)
        except Exception as e:
            logger.error(f"OpenClaw intent classification failed: {e}")
            return self._fallback_intent()
    
    def make_decision(self, context_text: str, intent: str) -> Dict[str, Any]:
        """
        Make decision on how to handle the issue
        
        Args:
            context_text: Full context
            intent: Detected intent
            
        Returns:
            Decision with action plan
        """
        prompt = self._build_decision_prompt(context_text, intent)
        
        try:
            result = self._call_openclaw(prompt)
            return self._parse_decision_response(result)
        except Exception as e:
            logger.error(f"OpenClaw decision making failed: {e}")
            return self._fallback_decision()
    
    def _build_intent_prompt(self, context_text: str) -> str:
        """Build prompt for intent classification"""
        return f"""你是一个专业的意图分类助手。分析用户的 GitHub Issue/评论，判断用户的真实意图。

## 分析步骤

1. **理解内容**：仔细阅读用户的描述，判断是否有代码需要修复
2. **判断类型**：
   - "answer": 询问、质疑、需要解释、讨论修改合理性
   - "modify": 代码修复请求、功能实现、bug修复、"帮我解决这个问题"
   - "research": 仅查询技术参数、规格、无需代码修改
   - "clarify": 信息不足，无法判断意图

3. **关键判断规则**（优先级从高到低）：
   
   **→ modify（代码修改）**：
   - "帮我解决"、"帮我修复"、"处理一下" + 代码/报错信息
   - "not working"、"报错"、"error"、"exception" + 代码
   - "修复"、"修改"、"改成"、"fix"、"bug"
   - 用户提供了代码片段且表示运行有问题
   - 用户说"XXX不工作"且涉及代码实现
   
   **→ research（仅查询）**：
   - "查询"、"查一下" + 芯片/硬件参数
   - "供电范围"、"电压"、"频率" + 芯片型号
   - 纯技术规格询问，无代码需要修改
   
   **→ answer（解释说明）**：
   - "为什么"、"怎么回事"、"解释一下"
   - 询问原理、讨论方案合理性

4. **重要区分**：
   - 如果用户提供了代码且表示"不工作/报错" → **modify**
   - 如果用户只是询问"这个芯片的供电是多少" → **research**
   - 如果用户说"帮我解决这个问题"且附带了代码 → **modify**

## 用户内容

```
{context_text}
```

## 输出格式

返回严格的 JSON：
```json
{{
  "intent": "answer|modify|research|clarify",
  "confidence": 0.0-1.0,
  "reasoning": "简要说明判断理由，特别是为什么选这个意图",
  "needs_research": true|false,
  "research_topics": ["如果需要查询，列出查询主题"]
}}
```

要求：
- confidence > 0.8 表示高置信度
- needs_research=true 仅在需要查询芯片手册等技术文档时
- 如果涉及代码修复，必须选 modify
- 只返回 JSON，不要其他内容"""
    
    def _build_decision_prompt(self, context_text: str, intent: str) -> str:
        """Build prompt for decision making"""
        return f"""你是一个决策助手。基于已识别的意图，制定具体的处理方案。

## 已识别的意图

{intent}

## 用户内容

```
{context_text}
```

## 任务

根据意图制定处理方案：

1. 如果 intent="answer":
   - 确定回复内容要点
   - 判断是否需要引用之前的修改

2. 如果 intent="modify":
   - 分析需要修改的文件
   - 确定修改策略
   - 评估复杂度 (simple/medium/complex)

3. 如果 intent="research":
   - 列出需要查询的知识点
   - 制定查询计划

## 输出格式

返回 JSON：
```json
{{
  "action": "reply|modify|research|skip",
  "complexity": "simple|medium|complex",
  "files_to_modify": ["file1.cpp", "file2.h"],
  "change_description": "修改说明",
  "confidence": 0.0-1.0,
  "response": "如果不修改，回复给用户的内容"
}}
```"""
    
    def intent_recognize(self, prompt: str) -> Dict[str, Any]:
        """
        Recognize user intent from a prompt (for comment/reply intent recognition)
        
        Args:
            prompt: The prompt containing the comment text and context
            
        Returns:
            Intent recognition result with keys: intent, confidence, reasoning
        """
        try:
            result = self._call_openclaw(prompt)
            # _call_openclaw 已经返回 dict，直接提取需要的字段
            return {
                "intent": result.get("intent", "unknown"),
                "confidence": float(result.get("confidence", 0.5)),
                "reasoning": result.get("reasoning", "")
            }
        except Exception as e:
            logger.error(f"OpenClaw intent recognition failed: {e}")
            return self._fallback_comment_intent()
    
    def _parse_comment_intent_response(self, result_text: str) -> Dict[str, Any]:
        """Parse comment intent response from OpenClaw"""
        try:
            # Try to extract JSON from the response
            json_match = re.search(r'```json\s*(.*?)\s*```', result_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                # Try to find JSON without markdown
                json_match = re.search(r'\{[^{}]*"intent"[^{}]*\}', result_text, re.DOTALL)
                if json_match:
                    json_str = json_match.group(0)
                else:
                    json_str = result_text
            
            data = json.loads(json_str)
            return {
                "intent": data.get("intent", "unknown"),
                "confidence": float(data.get("confidence", 0.5)),
                "reasoning": data.get("reasoning", "")
            }
        except Exception as e:
            logger.warning(f"Failed to parse intent response: {e}, using raw text")
            # Fallback: analyze text for common patterns
            text_lower = result_text.lower()
            if "confirm" in text_lower or "解决" in text_lower:
                return {"intent": "confirm_resolution", "confidence": 0.7, "reasoning": "Pattern match"}
            elif "deny" in text_lower or "没解决" in text_lower:
                return {"intent": "deny_resolution", "confidence": 0.7, "reasoning": "Pattern match"}
            else:
                return {"intent": "neutral", "confidence": 0.5, "reasoning": "Unknown"}
    
    def _fallback_comment_intent(self) -> Dict[str, Any]:
        """Fallback when AI is unavailable"""
        return {
            "intent": "unknown",
            "confidence": 0.0,
            "reasoning": "AI service unavailable"
        }
    
    def _cleanup_lock_files(self):
        """Clean up stale lock files"""
        try:
            import glob
            lock_dir = Path.home() / ".openclaw" / "agents" / self.agent / "sessions"
            if lock_dir.exists():
                for lock_file in lock_dir.glob("*.lock"):
                    try:
                        lock_file.unlink()
                        logger.debug(f"Removed stale lock file: {lock_file}")
                    except:
                        pass
        except Exception as e:
            logger.debug(f"Failed to cleanup lock files: {e}")
    
    def _call_openclaw(self, prompt: str, retry_count: int = 0) -> Dict[str, Any]:
        """Call OpenClaw CLI with retry"""
        # Clean up lock files before each call
        self._cleanup_lock_files()
        
        cmd = [
            "openclaw", "agent",
            "--agent", self.agent,
            "--local",
            "--json",
            "--message", prompt
        ]
        
        logger.debug(f"Calling OpenClaw with prompt length: {len(prompt)}")
        
        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self.timeout
            )
            
            if result.returncode != 0:
                # Check for lock file error
                if "session file locked" in result.stderr and retry_count < self.max_retries:
                    logger.warning(f"OpenClaw session locked, retrying ({retry_count + 1}/{self.max_retries})...")
                    import time
                    time.sleep(2)  # Wait for lock to be released
                    return self._call_openclaw(prompt, retry_count + 1)
                raise RuntimeError(f"OpenClaw failed: {result.stderr}")
            
            return json.loads(result.stdout)
            
        except subprocess.TimeoutExpired:
            if retry_count < self.max_retries:
                logger.warning(f"OpenClaw timeout, retrying ({retry_count + 1}/{self.max_retries})...")
                # Kill any hanging openclaw processes
                self._cleanup_hanging_processes()
                return self._call_openclaw(prompt, retry_count + 1)
            raise RuntimeError(f"OpenClaw timed out after {self.timeout}s")
    
    def _cleanup_hanging_processes(self):
        """Kill hanging openclaw processes"""
        try:
            import signal
            import psutil
            for proc in psutil.process_iter(['pid', 'name', 'cmdline']):
                try:
                    if proc.info['name'] == 'openclaw' or 'openclaw agent' in ' '.join(proc.info['cmdline'] or []):
                        logger.debug(f"Killing hanging openclaw process: {proc.info['pid']}")
                        os.kill(proc.info['pid'], signal.SIGTERM)
                except:
                    pass
        except Exception as e:
            logger.debug(f"Failed to cleanup processes: {e}")
    
    def _parse_intent_response(self, result: Dict) -> Dict[str, Any]:
        """Parse intent classification response"""
        text = ""
        for payload in result.get("payloads", []):
            text += payload.get("text", "") + "\n"
        
        logger.debug(f"OpenClaw response: {text[:200]}...")
        
        try:
            # Try JSON block
            match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                parsed = json.loads(match.group(1))
            else:
                # Try raw JSON
                match = re.search(r'(\{[\s\S]*"intent"[\s\S]*\})', text)
                if match:
                    parsed = json.loads(match.group(1))
                else:
                    raise ValueError("No JSON found in response")
            
            return {
                "intent": parsed.get("intent", "clarify"),
                "confidence": float(parsed.get("confidence", 0.5)),
                "reasoning": parsed.get("reasoning", ""),
                "needs_research": parsed.get("needs_research", False),
                "research_topics": parsed.get("research_topics", [])
            }
        except (json.JSONDecodeError, ValueError) as e:
            logger.error(f"Failed to parse intent response: {e}")
            return self._fallback_intent()
    
    def _parse_decision_response(self, result: Dict) -> Dict[str, Any]:
        """Parse decision response"""
        text = ""
        for payload in result.get("payloads", []):
            text += payload.get("text", "") + "\n"
        
        try:
            match = re.search(r'```json\s*(\{.*?\})\s*```', text, re.DOTALL)
            if match:
                return json.loads(match.group(1))
            match = re.search(r'(\{[\s\S]*"action"[\s\S]*\})', text)
            if match:
                return json.loads(match.group(1))
        except:
            pass
        
        return self._fallback_decision()
    
    def _fallback_intent(self) -> Dict[str, Any]:
        """Fallback when AI fails"""
        return {
            "intent": "modify",  # Default to modify to be safe
            "confidence": 0.3,
            "reasoning": "OpenClaw failed, defaulting to modify",
            "needs_research": False,
            "research_topics": []
        }
    
    def _fallback_decision(self) -> Dict[str, Any]:
        """Fallback decision"""
        return {
            "action": "reply",
            "complexity": "simple",
            "files_to_modify": [],
            "change_description": "AI service unavailable",
            "confidence": 0.3,
            "response": "🤖 服务暂时不可用，请稍后再试。"
        }
    
    def health_check(self) -> bool:
        """Check if OpenClaw is available"""
        try:
            result = subprocess.run(
                ["openclaw", "status"],
                capture_output=True,
                text=True,
                timeout=5
            )
            return result.returncode == 0
        except:
            return False
