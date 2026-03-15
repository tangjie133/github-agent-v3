"""
GitHub API 客户端

支持两种认证方式：
1. Personal Access Token (PAT) - 简单，适合个人使用
2. GitHub App - 更安全，适合组织使用
"""

import os
import time
import json
import base64
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
from datetime import datetime, timedelta

import aiohttp

from core.logging import get_logger, traced
from core.config import get_config

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


class GitHubAppAuth:
    """
    GitHub App 认证管理
    
    处理 JWT 签名和安装令牌获取
    """
    
    def __init__(self, app_id: str, private_key: str):
        self.app_id = app_id
        self.private_key = private_key
        self._installation_tokens: Dict[str, Dict] = {}  # repo -> {token, expires_at}
    
    def _generate_jwt(self) -> str:
        """生成 JWT token (PyJWT 2.x compatible)"""
        try:
            import jwt
        except ImportError:
            logger.error("github_app.missing_jwt_library")
            raise RuntimeError("PyJWT library required for GitHub App auth")
        
        now = int(time.time())
        payload = {
            "iat": now - 60,  # 发行时间（提前 60 秒避免时钟漂移）
            "exp": now + 600,  # 过期时间（10 分钟）
            "iss": self.app_id
        }
        
        # PyJWT 2.x API: 直接使用 jwt.encode() 传入私钥
        token = jwt.encode(payload, self.private_key, algorithm='RS256')
        
        # jwt.encode 返回 str (PyJWT 2.x)，无需解码
        return token
    
    async def _get_installation_token(self, 
                                     owner: str, 
                                     repo: str,
                                     session: aiohttp.ClientSession) -> str:
        """
        获取安装令牌
        
        令牌缓存 50 分钟（实际有效期 1 小时）
        """
        cache_key = f"{owner}/{repo}"
        
        # 检查缓存
        cached = self._installation_tokens.get(cache_key)
        if cached:
            expires_at = cached.get('expires_at', 0)
            if time.time() < expires_at - 600:  # 提前 10 分钟刷新
                return cached['token']
        
        # 获取新令牌
        jwt_token = self._generate_jwt()
        
        # 获取安装 ID（如果未提供）
        installation_id = await self._get_installation_id(
            owner, repo, jwt_token, session
        )
        
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        
        async with session.post(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github.v3+json"
            }
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            
            token = data['token']
            expires_at = data['expires_at']
            
            # 解析过期时间
            expires_dt = datetime.fromisoformat(expires_at.replace('Z', '+00:00'))
            expires_timestamp = expires_dt.timestamp()
            
            # 缓存
            self._installation_tokens[cache_key] = {
                'token': token,
                'expires_at': expires_timestamp
            }
            
            return token
    
    async def _get_installation_id(self,
                                   owner: str,
                                   repo: str,
                                   jwt_token: str,
                                   session: aiohttp.ClientSession) -> int:
        """获取仓库的安装 ID"""
        url = f"https://api.github.com/repos/{owner}/{repo}/installation"
        
        async with session.get(
            url,
            headers={
                "Authorization": f"Bearer {jwt_token}",
                "Accept": "application/vnd.github.v3+json"
            }
        ) as resp:
            resp.raise_for_status()
            data = await resp.json()
            return data['id']
    
    async def get_auth_headers(self,
                               owner: str,
                               repo: str,
                               session: aiohttp.ClientSession) -> Dict[str, str]:
        """获取认证头"""
        token = await self._get_installation_token(owner, repo, session)
        return {
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github.v3+json"
        }


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
        self._app_auth: Optional[GitHubAppAuth] = None
        
        # 初始化 GitHub App 认证
        if self.credentials.app_id and self.credentials.private_key:
            self._app_auth = GitHubAppAuth(
                self.credentials.app_id,
                self.credentials.private_key
            )
    
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
    
    async def _get_auth_headers(self, owner: str, repo: str) -> Dict[str, str]:
        """获取认证头"""
        if self._app_auth:
            session = await self._get_session()
            return await self._app_auth.get_auth_headers(owner, repo, session)
        
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