"""
GitHub API Async Client

异步封装 GitHub REST API 调用，支持：
- 连接池管理
- 自动重试
- 速率限制处理
- 统一的异常转换
"""

import base64
from typing import Optional, Dict, Any, List, Union
from urllib.parse import quote

import httpx
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log
)

from core.logging import get_logger
from core.exceptions import (
    GitHubAPIError,
    GitHubAuthError,
    GitHubRateLimitError,
    GitHubNotFoundError,
    handle_exception
)

logger = get_logger(__name__)


class GitHubClient:
    """
    异步 GitHub API 客户端
    
    使用 httpx.AsyncClient 实现异步 HTTP 调用，支持连接池复用
    """
    
    def __init__(
        self,
        auth_manager=None,
        installation_id: Optional[Union[str, int]] = None,
        token: Optional[str] = None,
        base_url: str = "https://api.github.com",
        timeout: float = 30.0,
        max_retries: int = 3
    ):
        """
        初始化 GitHub 客户端
        
        Args:
            auth_manager: GitHubAuthManager 实例
            installation_id: GitHub App 安装 ID
            token: 直接指定的 Token（优先于 auth_manager）
            base_url: GitHub API 基础 URL
            timeout: 请求超时时间
            max_retries: 最大重试次数
        """
        self.auth = auth_manager
        self.installation_id = str(installation_id) if installation_id is not None else None
        self._token = token
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        
        # 创建异步 HTTP 客户端
        limits = httpx.Limits(max_connections=100, max_keepalive_connections=20)
        timeout_config = httpx.Timeout(timeout, connect=10.0)
        
        self._client = httpx.AsyncClient(
            base_url=self.base_url,
            limits=limits,
            timeout=timeout_config,
            headers={
                "Accept": "application/vnd.github.v3+json",
                "X-GitHub-Api-Version": "2022-11-28"
            }
        )
    
    async def _get_token(self) -> str:
        """获取认证 Token"""
        if self._token:
            return self._token
        
        if self.auth:
            # 同步调用转异步
            import asyncio
            loop = asyncio.get_event_loop()
            return await loop.run_in_executor(
                None,
                self.auth.get_installation_token,
                self.installation_id
            )
        
        raise GitHubAuthError("No authentication available")
    
    async def _get_headers(self) -> Dict[str, str]:
        """获取请求头"""
        token = await self._get_token()
        return {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
            "X-GitHub-Api-Version": "2022-11-28"
        }
    
    def _handle_error(self, response: httpx.Response) -> None:
        """
        处理 HTTP 错误响应
        
        Args:
            response: HTTP 响应对象
        
        Raises:
            GitHubAPIError 及其子类
        """
        if response.status_code < 400:
            return
        
        # 尝试解析错误详情
        try:
            error_data = response.json()
            message = error_data.get("message", "Unknown error")
            errors = error_data.get("errors", [])
        except Exception:
            message = response.text or "Unknown error"
            errors = []
        
        # 根据状态码抛出特定异常
        if response.status_code == 401:
            raise GitHubAuthError(message)
        
        elif response.status_code == 404:
            raise GitHubNotFoundError(
                resource=response.request.url.path,
                details={"message": message}
            )
        
        elif response.status_code == 429:
            reset_at = response.headers.get("X-RateLimit-Reset")
            raise GitHubRateLimitError(
                reset_at=int(reset_at) if reset_at else None,
                details={"message": message}
            )
        
        else:
            raise GitHubAPIError(
                message=message,
                status_code=response.status_code,
                response_body=str(errors) if errors else None,
                details={"url": str(response.request.url)}
            )
    
    @retry(
        retry=retry_if_exception_type((GitHubRateLimitError, httpx.NetworkError)),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=60),
        reraise=True
    )
    async def _request(
        self,
        method: str,
        path: str,
        **kwargs
    ) -> httpx.Response:
        """
        发送 HTTP 请求（带重试）
        
        Args:
            method: HTTP 方法
            path: 请求路径
            **kwargs: 其他参数
        
        Returns:
            HTTP 响应对象
        """
        headers = await self._get_headers()
        
        # 合并 headers
        if "headers" in kwargs:
            headers.update(kwargs.pop("headers"))
        
        try:
            response = await self._client.request(
                method=method,
                url=path,
                headers=headers,
                **kwargs
            )
            
            # 处理速率限制
            if response.status_code == 429:
                reset_at = response.headers.get("X-RateLimit-Reset")
                raise GitHubRateLimitError(
                    reset_at=int(reset_at) if reset_at else None
                )
            
            self._handle_error(response)
            return response
            
        except (GitHubAPIError, GitHubRateLimitError):
            raise
        except httpx.HTTPStatusError as e:
            self._handle_error(e.response)
        except Exception as e:
            logger.error("github.request_failed", error=str(e))
            raise handle_exception(e)
    
    # ========================================================================
    # 仓库操作
    # ========================================================================
    
    async def get_repo_info(self, owner: str, repo: str) -> Dict[str, Any]:
        """
        获取仓库信息
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
        
        Returns:
            仓库信息字典
        """
        response = await self._request("GET", f"/repos/{owner}/{repo}")
        return response.json()
    
    # ========================================================================
    # Issue 操作
    # ========================================================================
    
    async def get_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int
    ) -> Dict[str, Any]:
        """
        获取 Issue 详情
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            issue_number: Issue 编号
        
        Returns:
            Issue 详情字典
        """
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/issues/{issue_number}"
        )
        return response.json()
    
    async def get_issue_comments(
        self,
        owner: str,
        repo: str,
        issue_number: int
    ) -> List[Dict[str, Any]]:
        """
        获取 Issue 的所有评论
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            issue_number: Issue 编号
        
        Returns:
            评论列表
        """
        comments = []
        page = 1
        per_page = 100
        
        while True:
            response = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
                params={"page": page, "per_page": per_page}
            )
            
            data = response.json()
            if not data:
                break
            
            comments.extend(data)
            
            if len(data) < per_page:
                break
            
            page += 1
        
        return comments
    
    async def create_issue_comment(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        body: str
    ) -> Dict[str, Any]:
        """
        在 Issue 上创建评论
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            issue_number: Issue 编号
            body: 评论内容
        
        Returns:
            创建的评论信息
        """
        response = await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            json={"body": body}
        )
        
        result = response.json()
        logger.info(
            "github.comment_created",
            repo=f"{owner}/{repo}",
            issue=issue_number,
            comment_id=result.get("id")
        )
        return result
    
    async def close_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int
    ) -> bool:
        """
        关闭 Issue
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            issue_number: Issue 编号
        
        Returns:
            是否成功关闭
        """
        try:
            await self._request(
                "PATCH",
                f"/repos/{owner}/{repo}/issues/{issue_number}",
                json={"state": "closed"}
            )
            logger.info("github.issue_closed", repo=f"{owner}/{repo}", issue=issue_number)
            return True
        except GitHubAPIError as e:
            logger.error("github.close_issue_failed", error=str(e))
            return False
    
    async def update_issue(
        self,
        owner: str,
        repo: str,
        issue_number: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        更新 Issue
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            issue_number: Issue 编号
            **kwargs: 更新字段（title, body, state, labels, assignees, milestone）
        
        Returns:
            更新后的 Issue 信息
        """
        response = await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            json=kwargs
        )
        return response.json()
    
    # ========================================================================
    # 文件操作
    # ========================================================================
    
    async def get_file_content(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main"
    ) -> Optional[str]:
        """
        获取文件内容
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            path: 文件路径
            ref: 分支或 commit SHA
        
        Returns:
            文件内容，文件不存在返回 None
        """
        try:
            response = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref}
            )
            
            data = response.json()
            
            if data.get("encoding") == "base64":
                return base64.b64decode(data["content"]).decode("utf-8")
            return data.get("content")
            
        except GitHubNotFoundError:
            return None
    
    async def get_file_sha(
        self,
        owner: str,
        repo: str,
        path: str,
        ref: str = "main"
    ) -> Optional[str]:
        """
        获取文件 SHA（用于更新文件）
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            path: 文件路径
            ref: 分支或 commit SHA
        
        Returns:
            文件 SHA，文件不存在返回 None
        """
        try:
            response = await self._request(
                "GET",
                f"/repos/{owner}/{repo}/contents/{path}",
                params={"ref": ref}
            )
            return response.json().get("sha")
        except GitHubNotFoundError:
            return None
    
    async def create_or_update_file(
        self,
        owner: str,
        repo: str,
        path: str,
        content: str,
        message: str,
        branch: str,
        sha: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        创建或更新文件
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            path: 文件路径
            content: 文件内容
            message: commit 信息
            branch: 分支名
            sha: 现有文件 SHA（更新时必须提供）
        
        Returns:
            操作结果
        """
        data = {
            "message": message,
            "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
            "branch": branch
        }
        
        if sha:
            data["sha"] = sha
        
        response = await self._request(
            "PUT",
            f"/repos/{owner}/{repo}/contents/{path}",
            json=data
        )
        
        result = response.json()
        logger.info(
            "github.file_updated",
            repo=f"{owner}/{repo}",
            path=path,
            branch=branch
        )
        return result
    
    # ========================================================================
    # 分支操作
    # ========================================================================
    
    async def get_branch_sha(self, owner: str, repo: str, branch: str) -> str:
        """
        获取分支的最新 commit SHA
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            branch: 分支名
        
        Returns:
            commit SHA
        """
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/git/refs/heads/{branch}"
        )
        return response.json()["object"]["sha"]
    
    async def create_branch(
        self,
        owner: str,
        repo: str,
        branch: str,
        from_branch: str = "main"
    ) -> Dict[str, Any]:
        """
        创建新分支
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            branch: 新分支名
            from_branch: 基于的分支
        
        Returns:
            分支信息
        """
        # 获取基础分支的 SHA
        base_sha = await self.get_branch_sha(owner, repo, from_branch)
        
        try:
            response = await self._request(
                "POST",
                f"/repos/{owner}/{repo}/git/refs",
                json={
                    "ref": f"refs/heads/{branch}",
                    "sha": base_sha
                }
            )
            
            logger.info(
                "github.branch_created",
                repo=f"{owner}/{repo}",
                branch=branch,
                from_branch=from_branch
            )
            return response.json()
            
        except GitHubAPIError as e:
            if e.status_code == 422 and "Reference already exists" in str(e):
                # 分支已存在，返回现有分支
                response = await self._request(
                    "GET",
                    f"/repos/{owner}/{repo}/git/refs/heads/{branch}"
                )
                return response.json()
            raise
    
    async def delete_branch(
        self,
        owner: str,
        repo: str,
        branch: str
    ) -> bool:
        """
        删除分支
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            branch: 分支名
        
        Returns:
            是否成功删除
        """
        try:
            await self._request(
                "DELETE",
                f"/repos/{owner}/{repo}/git/refs/heads/{branch}"
            )
            logger.info("github.branch_deleted", repo=f"{owner}/{repo}", branch=branch)
            return True
        except GitHubAPIError as e:
            logger.error("github.delete_branch_failed", error=str(e))
            return False
    
    # ========================================================================
    # Pull Request 操作
    # ========================================================================
    
    async def create_pull_request(
        self,
        owner: str,
        repo: str,
        title: str,
        head: str,
        base: str = "main",
        body: str = "",
        issue_number: Optional[int] = None
    ) -> Optional[Dict[str, Any]]:
        """
        创建 Pull Request
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            title: PR 标题
            head: 源分支
            base: 目标分支
            body: PR 描述
            issue_number: 关联的 Issue 编号
        
        Returns:
            PR 信息，失败返回 None
        """
        # 关联 Issue
        if issue_number:
            body = f"Closes #{issue_number}\n\n{body}"
        
        data = {
            "title": title,
            "head": head,
            "base": base,
            "body": body
        }
        
        try:
            response = await self._request(
                "POST",
                f"/repos/{owner}/{repo}/pulls",
                json=data
            )
            
            result = response.json()
            logger.info(
                "github.pr_created",
                repo=f"{owner}/{repo}",
                pr_number=result["number"],
                url=result["html_url"]
            )
            return result
            
        except GitHubAPIError as e:
            if e.status_code == 422:
                # 可能是 PR 已存在
                existing = await self.get_pull_request_by_branch(owner, repo, head)
                if existing:
                    logger.info(
                        "github.pr_already_exists",
                        repo=f"{owner}/{repo}",
                        pr_number=existing["number"]
                    )
                    return existing
            
            logger.error("github.create_pr_failed", error=str(e))
            return None
    
    async def get_pull_request_by_branch(
        self,
        owner: str,
        repo: str,
        head: str
    ) -> Optional[Dict[str, Any]]:
        """
        通过分支查找 PR
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            head: 源分支名
        
        Returns:
            PR 信息，未找到返回 None
        """
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls",
            params={
                "head": f"{owner}:{head}",
                "state": "open"
            }
        )
        
        prs = response.json()
        return prs[0] if prs else None
    
    async def get_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int
    ) -> Dict[str, Any]:
        """
        获取 PR 详情
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            pr_number: PR 编号
        
        Returns:
            PR 详情
        """
        response = await self._request(
            "GET",
            f"/repos/{owner}/{repo}/pulls/{pr_number}"
        )
        return response.json()
    
    async def update_pull_request(
        self,
        owner: str,
        repo: str,
        pr_number: int,
        **kwargs
    ) -> Dict[str, Any]:
        """
        更新 PR
        
        Args:
            owner: 仓库所有者
            repo: 仓库名
            pr_number: PR 编号
            **kwargs: 更新字段（title, body, state, base）
        
        Returns:
            更新后的 PR 信息
        """
        response = await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pr_number}",
            json=kwargs
        )
        return response.json()
    
    # ========================================================================
    # 辅助方法
    # ========================================================================
    
    async def get_installation_token(self) -> str:
        """获取安装 Token"""
        return await self._get_token()
    
    async def get_clone_url(self, owner: str, repo: str) -> str:
        """获取带认证的克隆 URL"""
        token = await self._get_token()
        return f"https://x-access-token:{token}@github.com/{owner}/{repo}.git"
    
    async def close(self):
        """关闭客户端，释放资源"""
        await self._client.aclose()
    
    async def __aenter__(self):
        """异步上下文管理器入口"""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """异步上下文管理器出口"""
        await self.close()
