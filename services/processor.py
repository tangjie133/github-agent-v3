"""
Issue 处理器服务

核心工作流：
1. 接收 Issue
2. 分析意图
3. 克隆仓库
4. 定位文件
5. 生成修复
6. 应用修复（自动或人工确认）
7. 创建 PR
8. 回复 Issue
"""

import asyncio
import time
from typing import Optional, Dict, Any
from pathlib import Path

from core.logging import get_logger, traced
from core.config import get_config
from core.i18n import t_detect, get_i18n
from core.confirmation import (
    get_confirmation_manager, ConfirmMode, ConfirmStatus, ConfirmationRecord
)
from core.fix.engine import get_fix_engine
from core.fix.models import FixPlan, FixResult, FixStatus
from core.git.operations import get_git_operations
from core.pr.manager import get_pr_manager
from core.github_api import get_github_client, GitHubClient

logger = get_logger(__name__)


class IssueProcessor:
    """
    Issue 处理器
    
    整合所有组件，完成 Issue 处理全流程
    """
    
    def __init__(self, github_client: Optional[GitHubClient] = None):
        self.config = get_config()
        self.github_client = github_client or get_github_client()
        
        # 子组件（延迟初始化）
        self._confirmation_mgr = None
        self._fix_engine = None
        self._git_ops = None
        self._pr_mgr = None
        
        # 初始化确认管理器的回调
        self._setup_confirmation_callbacks()
    
    def _setup_confirmation_callbacks(self):
        """设置确认机制的回调"""
        confirm_mgr = get_confirmation_manager()
        confirm_mgr.set_callbacks(
            on_confirm=self._on_fix_confirmed,
            on_reject=self._on_fix_rejected,
            on_timeout=self._on_fix_timeout
        )
    
    async def _get_fix_engine(self):
        if self._fix_engine is None:
            self._fix_engine = await get_fix_engine()
        return self._fix_engine
    
    def _get_git_ops(self):
        if self._git_ops is None:
            self._git_ops = get_git_operations()
        return self._git_ops
    
    def _get_pr_mgr(self):
        if self._pr_mgr is None:
            self._pr_mgr = get_pr_manager(self.github_client)
        return self._pr_mgr
    
    @traced("processor.handle_issue")
    async def handle_issue(self,
                          owner: str,
                          repo: str,
                          issue_number: int,
                          issue_title: str,
                          issue_body: str,
                          error_logs: str = "",
                          installation_id: Optional[int] = None) -> Dict[str, Any]:
        """
        处理 Issue 主入口
        
        完整工作流：
        1. 分析 Issue
        2. 克隆仓库
        3. 定位文件
        4. 生成修复
        5. 应用修复（根据确认模式）
        6. 创建 PR
        7. 回复用户
        """
        # 设置 GitHub App Installation ID
        if installation_id:
            self.github_client.set_installation_id(installation_id)
        
        start_time = time.time()
        lang = get_i18n().detect_language(issue_body)
        
        logger.info("processor.start",
                   owner=owner,
                   repo=repo,
                   issue=issue_number,
                   lang=lang)
        
        # 1. 发送处理中通知
        await self._comment_on_issue(
            owner, repo, issue_number,
            t_detect("processing_started", issue_body)
        )
        
        try:
            # 2. 分析 Issue
            fix_engine = await self._get_fix_engine()
            
            plan = await fix_engine.analyze_issue(
                issue_number=issue_number,
                repo=f"{owner}/{repo}",
                issue_title=issue_title,
                issue_body=issue_body,
                error_logs=error_logs
            )
            
            # 检查是否需要修复
            if not plan.affected_files:
                await self._comment_on_issue(
                    owner, repo, issue_number,
                    t_detect("error_no_fix_needed", issue_body)
                )
                return {"success": False, "reason": "no_fix_needed"}
            
            # 3. 克隆仓库
            await self._comment_on_issue(
                owner, repo, issue_number,
                t_detect("analyzing_code", issue_body)
            )
            
            repo_url = f"https://github.com/{owner}/{repo}.git"
            repo_path = await self._clone_repo(owner, repo, repo_url)
            
            if not repo_path:
                await self._comment_on_issue(
                    owner, repo, issue_number,
                    t_detect("failed", issue_body, reason="clone failed")
                )
                return {"success": False, "reason": "clone_failed"}
            
            # 4. 读取文件内容
            file_contents = await self._read_files(repo_path, plan.affected_files)
            
            if not file_contents:
                await self._comment_on_issue(
                    owner, repo, issue_number,
                    t_detect("error_cannot_locate", issue_body)
                )
                return {"success": False, "reason": "no_files_found"}
            
            # 5. 生成补丁
            await self._comment_on_issue(
                owner, repo, issue_number,
                t_detect("generating_fix", issue_body)
            )
            
            plan = await fix_engine.generate_patches(plan, file_contents)
            
            # 验证补丁
            validation = await fix_engine.validate_patches(plan)
            if not validation.is_valid:
                logger.error("processor.validation_failed",
                            errors=validation.errors)
            
            # 6. 应用修复
            await self._comment_on_issue(
                owner, repo, issue_number,
                t_detect("applying_fix", issue_body)
            )
            
            result = await self._apply_fix_with_confirmation(
                owner, repo, issue_number, plan, issue_body, lang
            )
            
            duration = time.time() - start_time
            
            logger.info("processor.complete",
                       owner=owner,
                       repo=repo,
                       issue=issue_number,
                       success=result.success,
                       duration=duration)
            
            return {
                "success": result.success,
                "pr_number": result.pr_number,
                "duration_seconds": duration,
                "message": result.message
            }
            
        except Exception as e:
            duration = time.time() - start_time
            logger.error("processor.error",
                        owner=owner,
                        repo=repo,
                        issue=issue_number,
                        error=str(e))
            
            await self._comment_on_issue(
                owner, repo, issue_number,
                t_detect("failed", issue_body, reason=str(e))
            )
            
            return {
                "success": False,
                "error": str(e),
                "duration_seconds": duration
            }
    
    async def _clone_repo(self, owner: str, repo: str, 
                         repo_url: str) -> Optional[Path]:
        """克隆仓库"""
        git_ops = self._get_git_ops()
        
        # 确定克隆策略
        # TODO: 根据仓库大小选择 shallow clone
        shallow = False
        
        result = await git_ops.clone(
            repo_url=repo_url,
            repo_name=f"{owner}__{repo}",
            shallow=shallow
        )
        
        if result.success:
            return result.path
        return None
    
    async def _read_files(self, repo_path: Path, 
                         file_locations) -> Dict[str, str]:
        """读取文件内容"""
        git_ops = self._get_git_ops()
        contents = {}
        
        for loc in file_locations:
            content = await git_ops.get_file_content(repo_path, loc.path)
            if content:
                contents[loc.path] = content
        
        return contents
    
    async def _apply_fix_with_confirmation(self,
                                          owner: str,
                                          repo: str,
                                          issue_number: int,
                                          plan: FixPlan,
                                          issue_body: str,
                                          lang: str) -> FixResult:
        """
        应用修复（支持人工确认）
        """
        confirm_mgr = get_confirmation_manager()
        git_ops = self._get_git_ops()
        pr_mgr = self._get_pr_mgr()
        
        # 获取文件列表
        files_changed = [p.path for p in plan.patches]
        
        # 创建分支
        branch_name = f"issue-{issue_number}-fix"
        repo_path = Path(self._get_git_ops().working_dir) / f"{owner}__{repo}"
        
        # 应用补丁到工作区
        for patch in plan.patches:
            if patch.change_type.value == 'add':
                await git_ops.write_file(
                    repo_path, patch.path, patch.new_content or ""
                )
            elif patch.change_type.value == 'modify':
                await git_ops.write_file(
                    repo_path, patch.path, patch.new_content or ""
                )
            elif patch.change_type.value == 'delete':
                await git_ops.delete_file(repo_path, patch.path)
        
        # 创建分支并提交
        success = await git_ops.create_branch(repo_path, branch_name)
        if not success:
            return FixResult(
                success=False,
                error="Failed to create branch",
                plan=plan
            )
        
        commit_msg = f"Fix #{issue_number}: {plan.title}"
        commit_result = await git_ops.commit_changes(
            repo_path, commit_msg, files=files_changed
        )
        
        if not commit_result.success:
            return FixResult(
                success=False,
                error=commit_result.error,
                plan=plan
            )
        
        # 推送分支
        push_success = await git_ops.push(repo_path, branch_name)
        if not push_success:
            return FixResult(
                success=False,
                error="Failed to push branch",
                plan=plan
            )
        
        # 根据确认模式处理
        if confirm_mgr.is_auto_mode():
            # 自动模式：直接创建正式 PR
            return await self._create_formal_pr(
                owner, repo, issue_number, plan, files_changed,
                branch_name, lang
            )
        else:
            # 人工确认模式：创建 Preview PR（Draft）
            return await self._create_preview_pr(
                owner, repo, issue_number, plan, files_changed,
                branch_name, issue_body, lang
            )
    
    async def _create_preview_pr(self,
                                owner: str,
                                repo: str,
                                issue_number: int,
                                plan: FixPlan,
                                files_changed: list,
                                branch_name: str,
                                issue_body: str,
                                lang: str) -> FixResult:
        """创建预览 PR（Draft）"""
        pr_mgr = self._get_pr_mgr()
        confirm_mgr = get_confirmation_manager()
        
        # 创建 Draft PR
        pr_info = await pr_mgr.create_pr(
            owner=owner,
            repo=repo,
            title=pr_mgr.generate_pr_title(plan.title, issue_number, lang),
            body=pr_mgr.generate_preview_pr_body(
                issue_body, plan.fix_strategy, files_changed, issue_number, lang
            ),
            head_branch=branch_name,
            is_draft=True,
            issue_number=issue_number
        )
        
        if not pr_info:
            return FixResult(
                success=False,
                error="Failed to create preview PR",
                plan=plan
            )
        
        # 创建确认记录
        record = await confirm_mgr.create_confirmation(
            repo=f"{owner}/{repo}",
            issue_number=issue_number,
            preview_pr_number=pr_info.number,
            files_changed=files_changed,
            issue_body=issue_body,
            confidence=plan.confidence
        )
        
        # 如果是自动确认的，直接转换
        if record.status == ConfirmStatus.AUTO:
            return await self._convert_preview_to_formal(
                owner, repo, record, plan, lang
            )
        
        # 在 Issue 中添加确认请求评论
        confirm_msg = confirm_mgr.get_confirmation_message(record, issue_body)
        await self._comment_on_issue(owner, repo, issue_number, confirm_msg)
        
        return FixResult(
            success=True,
            plan=plan,
            pr_number=pr_info.number,
            branch_name=branch_name,
            message=t_detect("fix_preview_title", issue_body)
        )
    
    async def _create_formal_pr(self,
                               owner: str,
                               repo: str,
                               issue_number: int,
                               plan: FixPlan,
                               files_changed: list,
                               branch_name: str,
                               lang: str) -> FixResult:
        """创建正式 PR"""
        pr_mgr = self._get_pr_mgr()
        
        pr_info = await pr_mgr.create_pr(
            owner=owner,
            repo=repo,
            title=pr_mgr.generate_pr_title(plan.title, issue_number, lang),
            body=pr_mgr.generate_pr_body(
                "", plan.fix_strategy, files_changed, issue_number, lang
            ),
            head_branch=branch_name,
            is_draft=False,
            issue_number=issue_number
        )
        
        if not pr_info:
            return FixResult(
                success=False,
                error="Failed to create PR",
                plan=plan
            )
        
        # 回复 Issue
        msg = t_detect("auto_applied_message", "", pr_number=pr_info.number)
        await self._comment_on_issue(owner, repo, issue_number, msg)
        
        return FixResult(
            success=True,
            plan=plan,
            pr_number=pr_info.number,
            branch_name=branch_name,
            message="Fix applied"
        )
    
    async def _convert_preview_to_formal(self,
                                        owner: str,
                                        repo: str,
                                        record: ConfirmationRecord,
                                        plan: FixPlan,
                                        lang: str) -> FixResult:
        """将 Preview PR 转换为正式 PR"""
        pr_mgr = self._get_pr_mgr()
        
        # 标记为就绪
        success = await pr_mgr.mark_ready_for_review(
            owner, repo, record.preview_pr_number
        )
        
        if success:
            # 更新 PR 描述
            await pr_mgr.update_pr(
                owner, repo, record.preview_pr_number,
                body=pr_mgr.generate_pr_body(
                    "", plan.fix_strategy, record.files_changed,
                    record.issue_number, lang
                )
            )
        
        return FixResult(
            success=success,
            plan=plan,
            pr_number=record.preview_pr_number,
            branch_name=f"issue-{record.issue_number}-fix",
            message="Preview PR converted to formal"
        )
    
    # ===== 确认回调 =====
    
    async def _on_fix_confirmed(self, record: ConfirmationRecord):
        """修复被确认时的回调"""
        logger.info("processor.fix_confirmed",
                   repo=record.repo,
                   issue=record.issue_number)
        
        # 转换 Preview PR 为正式 PR
        owner, repo = record.repo.split('/')
        pr_mgr = self._get_pr_mgr()
        
        await pr_mgr.mark_ready_for_review(
            owner, repo, record.preview_pr_number
        )
        
        # 回复 Issue
        msg = t_detect("confirmed_message", "")
        owner_name, repo_name = record.repo.split('/')
        await self._comment_on_issue(
            owner_name, repo_name, record.issue_number, msg
        )
    
    async def _on_fix_rejected(self, record: ConfirmationRecord):
        """修复被拒绝时的回调"""
        logger.info("processor.fix_rejected",
                   repo=record.repo,
                   issue=record.issue_number)
        
        # 关闭 Preview PR
        owner, repo = record.repo.split('/')
        pr_mgr = self._get_pr_mgr()
        
        await pr_mgr.close_pr(
            owner, repo, record.preview_pr_number,
            comment="Closed by user rejection"
        )
        
        # 回复 Issue
        msg = t_detect("rejected_message", "")
        owner_name, repo_name = record.repo.split('/')
        await self._comment_on_issue(
            owner_name, repo_name, record.issue_number, msg
        )
    
    async def _on_fix_timeout(self, record: ConfirmationRecord):
        """修复超时时的回调"""
        logger.info("processor.fix_timeout",
                   repo=record.repo,
                   issue=record.issue_number)
        
        # 关闭 Preview PR
        owner, repo = record.repo.split('/')
        pr_mgr = self._get_pr_mgr()
        
        await pr_mgr.close_pr(
            owner, repo, record.preview_pr_number,
            comment="Closed due to timeout (no response)"
        )
    
    # ===== 辅助方法 =====
    
    async def _comment_on_issue(self, owner: str, repo: str, 
                                issue_number: int, body: str):
        """在 Issue 中添加评论"""
        try:
            await self.github_client.create_issue_comment(
                owner, repo, issue_number, body
            )
            logger.debug("processor.comment_sent",
                        owner=owner, repo=repo, issue=issue_number)
        except Exception as e:
            logger.error("processor.comment_failed",
                        owner=owner,
                        repo=repo,
                        issue=issue_number,
                        error=str(e))
    
    async def handle_comment(self,
                            owner: str,
                            repo: str,
                            issue_number: int,
                            comment_body: str,
                            username: str) -> Optional[ConfirmStatus]:
        """
        处理用户评论（用于确认机制）
        
        返回确认状态，如果不是确认相关评论则返回 None
        """
        confirm_mgr = get_confirmation_manager()
        
        return await confirm_mgr.handle_user_response(
            repo, issue_number, comment_body, username
        )


# 全局实例
_processor: Optional[IssueProcessor] = None


async def get_issue_processor(github_client: Optional[GitHubClient] = None) -> IssueProcessor:
    """获取 IssueProcessor 实例"""
    global _processor
    if _processor is None:
        _processor = IssueProcessor(github_client)
    return _processor