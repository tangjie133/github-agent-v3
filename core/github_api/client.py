"""
GitHub API 客户端

支持两种认证方式：
1. Personal Access Token (PAT) - 简单，适合个人使用
2. GitHub App - 更安全，适合组织使用
"""

import os
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

import aiohttp

from core.logging import get_logger, traced
from core.config import get_config
from core.github_api.auth import GitHubAuthManager

logger = get_logger(__name__)


@dataclass
class GitHubCredentials:
    """GitHub 认证信息"""
    # PAT 模式
    token: Optional[str] = None
    
    # GitHub App 模式
    app_id: Optional[str] = None
    private_key: Optional[str] = None
    installation_id: Optional[int] = None


class GitHubClient:
    """
    GitHub API 客户端
    
    统一的 GitHub API 访问接口
    """
    
    BASE_URL = "https://api.github.com"
    
    def __init__(self, credentials: Optional[GitHubCredentials] = None):
        self.config = get_config()
        self.credentials = credentials or self._load_credentials()
        self._session: Optional[aiohttp.ClientSession] = None
        self._auth_manager: Optional[GitHubAuthManager] = None
        self._installation_id: Optional[str] = None
        
        # 初始化 GitHub App 认证管理器
        if self.credentials.app_id and self.credentials.private_key:
            self._auth_manager = GitHubAuthManager(
                app_id=self.credentials.app_id,
                private_key=self.credentials.private_key
            )
    
    def set_installation_id(self, installation_id: Optional[int]):
        """设置 GitHub App Installation ID（从 webhook 获取）"""
        self._installation_id = str(installation_id) if installation_id else None
    
    def _load_credentials(self) -> GitHubCredentials:
        """从配置加载认证信息"""
        # 优先从环境变量读取
        token = os.getenv("GITHUB_TOKEN")
        app_id = os.getenv("GITHUB_APP_ID")
        private_key = os.getenv("GITHUB_APP_PRIVATE_KEY")
        private_key_path = os.getenv("GITHUB_APP_PRIVATE_KEY_PATH")
        
        # 如果环境变量有私钥路径，从文件读取
        if private_key_path and not private_key:
            if os.path.exists(private_key_path):
                try:
                    with open(private_key_path) as f:
                        private_key = f.read()
                except Exception as e:
                    logger.error("github_api.failed_to_load_private_key",
                                path=private_key_path,
                                error=str(e))
                    private_key = None
            else:
                logger.error("github_api.private_key_file_not_found",
                            path=private_key_path)
                private_key = None
        
        # 如果从配置文件读取（环境变量未设置时）
        if not token and not app_id:
            token = self.config.github.token
            app_id = self.config.github.app_id
            
            # 如果环境变量没有私钥，尝试从配置读取
            if not private_key:
                private_key_path = self.config.github.private_key_path
                if private_key_path and os.path.exists(private_key_path):
                    try:
                        with open(private_key_path) as f:
                            private_key = f.read()
                    except Exception as e:
                        logger.error("github_api.failed_to_load_private_key",
                                    path=private_key_path,
                                    error=str(e))
                        private_key = None
        
        return GitHubCredentials(
            token=token,
            app_id=app_id,
            private_key=private_key
        )
    
    async def _get_session(self) -> aiohttp.ClientSession:
        """获取 HTTP session"""
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session
    
    async def _get_auth_headers(self, owner: str = "", repo: str = "") -> Dict[str, str]:
        """获取认证头"""
        if self._auth_manager and self._installation_id:
            # GitHub App 模式 - 使用 webhook 中的 installation_id
            token = self._auth_manager.get_installation_token(self._installation_id)
            return {
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github.v3+json"
            }
        
        if self.credentials.token:
            return {
                "Authorization": f"Bearer {self.credentials.token}",
                "Accept": "application/vnd.github.v3+json"
            }
        
        raise RuntimeError("No GitHub credentials configured")
    
    async def _request(self,
                      method: str,
                      endpoint: str,
                      owner: str = "",
                      repo: str = "",
                      **kwargs) -> Dict[str, Any]:
        """
        发送 API 请求
        """
        url = f"{self.BASE_URL}{endpoint}"
        
        session = await self._get_session()
        headers = await self._get_auth_headers(owner, repo)
        
        if 'headers' in kwargs:
            headers.update(kwargs.pop('headers'))
        
        logger.debug("github_api.request",
                    method=method,
                    endpoint=endpoint)
        
        async with session.request(
            method,
            url,
            headers=headers,
            **kwargs
        ) as resp:
            resp.raise_for_status()
            
            if resp.status == 204:  # No Content
                return {}
            
            return await resp.json()
    
    # ========== Issue API ==========
    
    @traced("github.get_issue")
    async def get_issue(self, owner: str, repo: str, 
                       issue_number: int) -> Optional[Dict]:
        """获取 Issue 详情"""
        try:
            return await self._request(
                "GET",
                f"/repos/{owner}/{repo}/issues/{issue_number}",
                owner=owner,
                repo=repo
            )
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise
    
    @traced("github.create_issue_comment")
    async def create_issue_comment(self, owner: str, repo: str,
                                   issue_number: int, body: str) -> Dict:
        """在 Issue 中添加评论"""
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{issue_number}/comments",
            owner=owner,
            repo=repo,
            json={"body": body}
        )
    
    @traced("github.update_issue")
    async def update_issue(self, owner: str, repo: str,
                          issue_number: int, **kwargs) -> Dict:
        """更新 Issue"""
        return await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/issues/{issue_number}",
            owner=owner,
            repo=repo,
            json=kwargs
        )
    
    # ========== PR API ==========
    
    @traced("github.create_pull")
    async def create_pull(self,
                         owner: str,
                         repo: str,
                         title: str,
                         body: str,
                         head: str,
                         base: str,
                         draft: bool = False) -> Dict:
        """创建 Pull Request"""
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/pulls",
            owner=owner,
            repo=repo,
            json={
                "title": title,
                "body": body,
                "head": head,
                "base": base,
                "draft": draft
            }
        )
    
    @traced("github.get_pull")
    async def get_pull(self, owner: str, repo: str,
                      pull_number: int) -> Optional[Dict]:
        """获取 PR 详情"""
        try:
            return await self._request(
                "GET",
                f"/repos/{owner}/{repo}/pulls/{pull_number}",
                owner=owner,
                repo=repo
            )
        except aiohttp.ClientResponseError as e:
            if e.status == 404:
                return None
            raise
    
    @traced("github.update_pull")
    async def update_pull(self, owner: str, repo: str,
                         pull_number: int, **kwargs) -> Dict:
        """更新 PR"""
        return await self._request(
            "PATCH",
            f"/repos/{owner}/{repo}/pulls/{pull_number}",
            owner=owner,
            repo=repo,
            json=kwargs
        )
    
    @traced("github.create_pr_comment")
    async def create_pr_comment(self, owner: str, repo: str,
                               pr_number: int, body: str) -> Dict:
        """在 PR 中添加评论"""
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/comments",
            owner=owner,
            repo=repo,
            json={"body": body}
        )
    
    @traced("github.add_labels_to_pr")
    async def add_labels_to_pr(self, owner: str, repo: str,
                              pr_number: int, labels: List[str]) -> Dict:
        """为 PR 添加标签"""
        return await self._request(
            "POST",
            f"/repos/{owner}/{repo}/issues/{pr_number}/labels",
            owner=owner,
            repo=repo,
            json={"labels": labels}
        )
    
    # ========== Repository API ==========
    
    @traced("github.get_repo")
    async def get_repo(self, owner: str, repo: str) -> Dict:
        """获取仓库信息"""
        return await self._request(
            "GET",
            f"/repos/{owner}/{repo}",
            owner=owner,
            repo=repo
        )
    
    async def close(self):
        """关闭 session"""
        if self._session and not self._session.closed:
            await self._session.close()
    
    async def __aenter__(self):
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()


# 全局实例
_github_client: Optional[GitHubClient] = None


def get_github_client() -> GitHubClient:
    """获取 GitHubClient 单例"""
    global _github_client
    if _github_client is None:
        _github_client = GitHubClient()
    return _github_client
