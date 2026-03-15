"""
Core data models for GitHub Agent V2
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional, Any
from enum import Enum
from datetime import datetime


class IntentType(Enum):
    """Intent classification types"""
    ANSWER = "answer"       # User is asking a question
    MODIFY = "modify"       # User wants code changes
    RESEARCH = "research"   # Needs investigation
    CLARIFY = "clarify"     # Insufficient information


class ProcessingStatus(Enum):
    """Processing status"""
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class IntentResult:
    """Result from intent classification"""
    intent: IntentType
    confidence: float
    reasoning: str
    needs_research: bool = False
    research_topics: List[str] = field(default_factory=list)
    
    def is_action_required(self) -> bool:
        """Check if this intent requires code modification"""
        return self.intent == IntentType.MODIFY


@dataclass
class GitHubEvent:
    """GitHub webhook event"""
    event_type: str  # issues, issue_comment, pull_request
    action: str      # opened, edited, created, etc.
    repository: Dict[str, Any]
    issue: Optional[Dict[str, Any]] = None
    comment: Optional[Dict[str, Any]] = None
    installation: Optional[Dict[str, Any]] = None
    sender: Optional[Dict[str, Any]] = None
    
    @property
    def repo_full_name(self) -> str:
        """Get repository full name (owner/repo)"""
        return self.repository.get("full_name", "")
    
    @property
    def installation_id(self) -> Optional[int]:
        """Get installation ID"""
        if self.installation:
            return self.installation.get("id")
        return None


@dataclass
class IssueContext:
    """Complete issue context"""
    issue_number: int
    title: str
    body: str
    author: str
    labels: List[str] = field(default_factory=list)
    comments: List[Dict[str, Any]] = field(default_factory=list)
    current_instruction: str = ""  # The triggering comment
    
    def build_full_context(self) -> str:
        """Build complete context string for AI"""
        context_parts = []
        
        if self.current_instruction:
            context_parts.append(f"【当前指令】{self.current_instruction}\n")
        
        context_parts.append(f"=== Issue 原始内容 ===")
        context_parts.append(f"标题: {self.title}")
        context_parts.append(f"内容: {self.body}\n")
        
        if self.comments:
            context_parts.append("=== Issue 讨论历史 ===")
            for i, comment in enumerate(self.comments, 1):
                author = comment.get("user", {}).get("login", "unknown")
                body = comment.get("body", "")
                context_parts.append(f"\n[评论 {i}] {author}:\n{body}\n")
        
        return "\n".join(context_parts)


@dataclass
class KBResult:
    """Knowledge base query result"""
    query: str
    results: List[Dict[str, Any]] = field(default_factory=list)
    answer: str = ""
    
    @property
    def best_match(self) -> Optional[Dict[str, Any]]:
        """Get best matching result"""
        if self.results:
            return self.results[0]
        return None
    
    @property
    def best_similarity(self) -> float:
        """Get best match similarity"""
        if self.best_match:
            return self.best_match.get("similarity", 0.0)
        return 0.0


@dataclass
class CodeChange:
    """Code change description"""
    file_path: str
    original_content: str
    modified_content: str
    change_description: str = ""
    
    @property
    def has_changes(self) -> bool:
        """Check if there are actual changes"""
        return self.original_content != self.modified_content


@dataclass
class ProcessingResult:
    """Issue processing result"""
    status: ProcessingStatus
    issue_number: int
    intent: Optional[IntentType] = None
    message: str = ""
    pull_request_url: str = ""
    pull_request_number: int = 0
    files_modified: List[str] = field(default_factory=list)
    change_description: str = ""
    error: str = ""
    
    def is_success(self) -> bool:
        return self.status == ProcessingStatus.COMPLETED


@dataclass
class IssueState:
    """Track issue processing state"""
    issue_number: int
    repo_full_name: str
    processed_at: datetime = field(default_factory=datetime.now)
    intent: Optional[IntentType] = None
    pull_request_number: int = 0
    pull_request_url: str = ""
    branch_name: str = ""
    processing_count: int = 0
    last_action: str = ""
    follow_up_count: int = 0
    processed_comment_ids: List[int] = field(default_factory=list)  # 已处理的评论ID
    issue_state: str = ""  # Issue 状态 (open/closed)
    
    @property
    def last_action_time(self) -> datetime:
        """Get last action time (same as processed_at for now)"""
        return self.processed_at
    
    def record_processing(self, action: str):
        """Record a processing action"""
        self.processing_count += 1
        self.last_action = action
    
    def is_comment_processed(self, comment_id: int) -> bool:
        """Check if a comment has been processed"""
        return comment_id in self.processed_comment_ids
    
    def record_comment(self, comment_id: int):
        """Record a processed comment ID"""
        if comment_id not in self.processed_comment_ids:
            self.processed_comment_ids.append(comment_id)
            # Keep only last 100 comment IDs to prevent memory bloat
            if len(self.processed_comment_ids) > 100:
                self.processed_comment_ids = self.processed_comment_ids[-100:]
