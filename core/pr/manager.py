"""
PR (Pull Request) 管理器

功能：
- 创建 PR
- 更新 PR
- Draft PR（预览模式）
- PR 状态管理
"""

from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from enum import Enum

from core.logging import get_logger, traced
from core.config import get_config
from core.i18n import t_detect
from core.github_api import get_github_client, GitHubClient

logger = get_logger(__name__)


class PRStatus(Enum):
    """PR 状态"""
    OPEN = "open"
    CLOSED = "closed"
    MERGED = "merged"
    DRAFT = "draft"


@dataclass
class PRInfo:
    """PR 信息"""
    number: int
    title: str
    body: str
    head_branch: str
    base_branch: str
    status: PRStatus
    is_draft: bool
    url: str
    html_url: str
    created_at: str
    updated_at: str


class PRManager:
    """
    PR 管理器
    
    处理所有 PR 相关操作
    """
    
    def __init__(self, github_client: Optional[GitHubClient] = None):
        self.config = get_config()
        self.github = github_client or get_github_client()
    
    @traced("pr.create")
    async def create_pr(self,
                       owner: str,
                       repo: str,
                       title: str,
                       body: str,
                       head_branch: str,
                       base_branch: str = "main",
                       is_draft: bool = False,
                       labels: Optional[List[str]] = None,
                       issue_number: Optional[int] = None) -> Optional[PRInfo]:
        """
        创建 Pull Request
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            title: PR 标题
            body: PR 描述
            head_branch: 源分支
            base_branch: 目标分支
            is_draft: 是否为 Draft PR
            labels: 标签列表
            issue_number: 关联的 Issue 编号
        
        Returns:
            PR 信息，失败返回 None
        """
        try:
            # 添加关联 Issue 的引用
            if issue_number:
                body = f"Fixes #{issue_number}\n\n{body}"
            
            # 创建 PR
            pr_data = await self.github.create_pull(
                owner=owner,
                repo=repo,
                title=title,
                body=body,
                head=head_branch,
                base=base_branch,
                draft=is_draft
            )
            
            if not pr_data:
                logger.error("pr.create_failed",
                            owner=owner,
                            repo=repo,
                            branch=head_branch)
                return None
            
            # 添加标签
            if labels:
                try:
                    await self.github.add_labels_to_pr(
                        owner=owner,
                        repo=repo,
                        pr_number=pr_data['number'],
                        labels=labels
                    )
                except Exception as e:
                    logger.warning("pr.add_labels_failed",
                                  owner=owner,
                                  repo=repo,
                                  pr_number=pr_data['number'],
                                  error=str(e))
            
            logger.info("pr.created",
                       owner=owner,
                       repo=repo,
                       pr_number=pr_data['number'],
                       draft=is_draft)
            
            return PRInfo(
                number=pr_data['number'],
                title=pr_data['title'],
                body=pr_data['body'],
                head_branch=head_branch,
                base_branch=base_branch,
                status=PRStatus.DRAFT if is_draft else PRStatus.OPEN,
                is_draft=is_draft,
                url=pr_data.get('url', ''),
                html_url=pr_data.get('html_url', ''),
                created_at=pr_data.get('created_at', ''),
                updated_at=pr_data.get('updated_at', '')
            )
            
        except Exception as e:
            logger.error("pr.create_exception",
                        owner=owner,
                        repo=repo,
                        error=str(e))
            return None
    
    @traced("pr.update")
    async def update_pr(self,
                       owner: str,
                       repo: str,
                       pr_number: int,
                       title: Optional[str] = None,
                       body: Optional[str] = None,
                       state: Optional[str] = None) -> bool:
        """
        更新 PR
        """
        try:
            updates = {}
            if title:
                updates['title'] = title
            if body:
                updates['body'] = body
            if state:
                updates['state'] = state
            
            if updates:
                await self.github.update_pull(
                    owner=owner,
                    repo=repo,
                    pull_number=pr_number,
                    **updates
                )
            
            logger.info("pr.updated",
                       owner=owner,
                       repo=repo,
                       pr_number=pr_number)
            return True
            
        except Exception as e:
            logger.error("pr.update_failed",
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        error=str(e))
            return False
    
    @traced("pr.close")
    async def close_pr(self,
                      owner: str,
                      repo: str,
                      pr_number: int,
                      comment: Optional[str] = None) -> bool:
        """
        关闭 PR
        """
        try:
            # 先添加评论
            if comment:
                await self.github.create_pr_comment(
                    owner=owner,
                    repo=repo,
                    pr_number=pr_number,
                    body=comment
                )
            
            # 关闭 PR
            await self.github.update_pull(
                owner=owner,
                repo=repo,
                pull_number=pr_number,
                state='closed'
            )
            
            logger.info("pr.closed",
                       owner=owner,
                       repo=repo,
                       pr_number=pr_number)
            return True
            
        except Exception as e:
            logger.error("pr.close_failed",
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        error=str(e))
            return False
    
    @traced("pr.mark_ready")
    async def mark_ready_for_review(self,
                                   owner: str,
                                   repo: str,
                                   pr_number: int) -> bool:
        """
        将 Draft PR 标记为就绪
        """
        try:
            # GitHub API: 更新 draft 状态
            await self.github.update_pull(
                owner=owner,
                repo=repo,
                pull_number=pr_number,
                draft=False
            )
            
            logger.info("pr.marked_ready",
                       owner=owner,
                       repo=repo,
                       pr_number=pr_number)
            return True
            
        except Exception as e:
            logger.error("pr.mark_ready_failed",
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        error=str(e))
            return False
    
    async def get_pr(self,
                    owner: str,
                    repo: str,
                    pr_number: int) -> Optional[PRInfo]:
        """
        获取 PR 信息
        """
        try:
            pr_data = await self.github.get_pull(
                owner=owner,
                repo=repo,
                pull_number=pr_number
            )
            
            if not pr_data:
                return None
            
            return PRInfo(
                number=pr_data['number'],
                title=pr_data['title'],
                body=pr_data['body'],
                head_branch=pr_data['head']['ref'],
                base_branch=pr_data['base']['ref'],
                status=PRStatus(pr_data['state']),
                is_draft=pr_data.get('draft', False),
                url=pr_data.get('url', ''),
                html_url=pr_data.get('html_url', ''),
                created_at=pr_data.get('created_at', ''),
                updated_at=pr_data.get('updated_at', '')
            )
            
        except Exception as e:
            logger.error("pr.get_failed",
                        owner=owner,
                        repo=repo,
                        pr_number=pr_number,
                        error=str(e))
            return None
    
    def generate_pr_title(self, issue_title: str, issue_number: int,
                         lang: str = "en") -> str:
        """
        生成 PR 标题
        """
        if lang == "zh":
            return f"修复 #{issue_number}: {issue_title}"
        return f"Fix #{issue_number}: {issue_title}"
    
    def generate_pr_body(self,
                        issue_body: str,
                        fix_description: str,
                        files_changed: List[str],
                        issue_number: int,
                        lang: str = "en") -> str:
        """
        生成 PR 描述
        """
        if lang == "zh":
            lines = [
                f"## 修复说明",
                f"",
                f"{fix_description}",
                f"",
                f"## 关联 Issue",
                f"Fixes #{issue_number}",
                f"",
                f"## 修改文件",
            ]
        else:
            lines = [
                f"## Description",
                f"",
                f"{fix_description}",
                f"",
                f"## Related Issue",
                f"Fixes #{issue_number}",
                f"",
                f"## Files Changed",
            ]
        
        for f in files_changed:
            lines.append(f"- `{f}`")
        
        lines.extend([
            "",
            "---",
            "*This PR was generated by GitHub Agent*"
        ])
        
        return "\n".join(lines)
    
    def generate_preview_pr_body(self,
                                issue_body: str,
                                fix_description: str,
                                files_changed: List[str],
                                issue_number: int,
                                lang: str = "en") -> str:
        """
        生成 Preview PR 描述（人工确认模式）
        """
        if lang == "zh":
            lines = [
                f"## 🚧 修复方案预览 (Preview)",
                f"",
                f"> ⚠️ **此 PR 为预览版本，等待人工确认后才会正式创建**",
                f"",
                f"### 修复说明",
                f"{fix_description}",
                f"",
                f"### 关联 Issue",
                f"#{issue_number}",
                f"",
                f"### 修改文件",
            ]
        else:
            lines = [
                f"## 🚧 Fix Preview",
                f"",
                f"> ⚠️ **This is a preview PR. It will be converted to formal PR after confirmation.**",
                f"",
                f"### Description",
                f"{fix_description}",
                f"",
                f"### Related Issue",
                f"#{issue_number}",
                f"",
                f"### Files Changed",
            ]
        
        for f in files_changed:
            lines.append(f"- `{f}`")
        
        if lang == "zh":
            lines.extend([
                "",
                "### 如何确认",
                "1. 查看此 PR 的代码更改",
                "2. 在关联 Issue 中回复 `确认` 或 `拒绝`",
                "3. 也可以在 PR 页面直接评论反馈",
            ])
        else:
            lines.extend([
                "",
                "### How to Confirm",
                "1. Review the code changes in this PR",
                "2. Reply `confirm` or `reject` in the related Issue",
                "3. Or comment directly on this PR",
            ])
        
        lines.extend([
            "",
            "---",
            "*This PR was generated by GitHub Agent*"
        ])
        
        return "\n".join(lines)


# 全局实例
_pr_manager: Optional[PRManager] = None


def get_pr_manager(github_client: Optional[GitHubClient] = None) -> PRManager:
    """获取 PRManager 实例"""
    global _pr_manager
    if _pr_manager is None:
        _pr_manager = PRManager(github_client)
    return _pr_manager