"""
GitHub App Authentication Manager

处理 JWT 生成和 Installation Token 获取
支持 Token 缓存和自动刷新
"""

import os
import time
import jwt
import httpx
from typing import Optional, Dict, Tuple
from pathlib import Path

from core.logging import get_logger
from core.exceptions import GitHubAuthError, ConfigError

logger = get_logger(__name__)


class GitHubAuthManager:
    """
    GitHub App 认证管理器
    
    功能：
    - JWT 生成（用于 GitHub App 认证）
    - Installation Token 获取和缓存
    - 自动 Token 刷新
    """
    
    # Token 过期前提前刷新的时间（秒）
    TOKEN_REFRESH_BUFFER = 300  # 5 分钟
    
    def __init__(
        self,
        app_id: Optional[str] = None,
        private_key_path: Optional[str] = None,
        private_key: Optional[str] = None
    ):
        """
        初始化认证管理器
        
        Args:
            app_id: GitHub App ID
            private_key_path: 私钥文件路径
            private_key: 直接传入私钥内容（优先于 private_key_path）
        
        Raises:
            ConfigError: 配置无效
        """
        self.app_id = app_id or os.environ.get("GITHUB_APP_ID")
        self.private_key_path = private_key_path or os.environ.get(
            "GITHUB_APP_PRIVATE_KEY_PATH"
        )
        self._private_key = private_key
        
        # Token 缓存: {installation_id: (token, expiry_timestamp)}
        self._installation_tokens: Dict[str, Tuple[str, float]] = {}
        
        # 验证配置
        self._validate_config()
    
    def _validate_config(self) -> None:
        """验证配置是否完整"""
        if not self.app_id:
            raise ConfigError(
                "GitHub App ID is required",
                details={"source": "GITHUB_APP_ID env var or app_id parameter"}
            )
        
        if self._private_key is None and not self.private_key_path:
            raise ConfigError(
                "GitHub App private key is required",
                details={
                    "source": "GITHUB_APP_PRIVATE_KEY_PATH env var, "
                             "private_key_path parameter, or private_key parameter"
                }
            )
        
        if self.private_key_path:
            key_path = Path(self.private_key_path)
            if not key_path.exists():
                raise ConfigError(
                    f"Private key file not found: {self.private_key_path}",
                    details={"path": str(key_path.absolute())}
                )
    
    def _load_private_key(self) -> str:
        """
        加载私钥
        
        Returns:
            私钥内容
        
        Raises:
            GitHubAuthError: 加载失败
        """
        if self._private_key is not None:
            return self._private_key
        
        try:
            key_path = Path(self.private_key_path)
            with open(key_path, 'r', encoding='utf-8') as f:
                self._private_key = f.read()
            return self._private_key
        except Exception as e:
            raise GitHubAuthError(
                f"Failed to load private key: {e}",
                details={"path": self.private_key_path}
            )
    
    def _generate_jwt(self) -> str:
        """
        生成 JWT Token
        
        Returns:
            JWT Token 字符串
        
        Raises:
            GitHubAuthError: 生成失败
        """
        now = int(time.time())
        
        payload = {
            "iat": now - 60,  # 签发时间（60秒前，避免时钟偏差）
            "exp": now + 600,  # 过期时间（10分钟后）
            "iss": self.app_id
        }
        
        try:
            private_key = self._load_private_key()
            return jwt.encode(payload, private_key, algorithm="RS256")
        except jwt.PyJWTError as e:
            raise GitHubAuthError(
                f"Failed to generate JWT: {e}",
                details={"error_type": type(e).__name__}
            )
    
    def get_installation_token(self, installation_id: Optional[str] = None) -> str:
        """
        获取 Installation Access Token
        
        Token 会被缓存，过期前自动刷新
        
        Args:
            installation_id: GitHub App Installation ID
        
        Returns:
            Installation Access Token
        
        Raises:
            GitHubAuthError: 获取失败
        """
        if installation_id is None:
            raise GitHubAuthError(
                "Installation ID is required",
                details={"help": "Provide installation_id from webhook payload"}
            )
        
        # 确保是字符串
        installation_id = str(installation_id)
        
        # 检查缓存
        if installation_id in self._installation_tokens:
            token, expiry = self._installation_tokens[installation_id]
            # 如果 Token 还没过期（考虑提前刷新缓冲）
            if time.time() < expiry - self.TOKEN_REFRESH_BUFFER:
                logger.debug(
                    "github.using_cached_token",
                    installation_id=installation_id,
                    expires_in=int(expiry - time.time())
                )
                return token
            else:
                logger.debug(
                    "github.token_expiring_soon",
                    installation_id=installation_id
                )
        
        # 获取新 Token
        return self._fetch_new_token(installation_id)
    
    def _fetch_new_token(self, installation_id: str) -> str:
        """
        从 GitHub API 获取新的 Installation Token
        
        Args:
            installation_id: Installation ID
        
        Returns:
            新的 Access Token
        
        Raises:
            GitHubAuthError: 获取失败
        """
        jwt_token = self._generate_jwt()
        
        headers = {
            "Authorization": f"Bearer {jwt_token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        url = f"https://api.github.com/app/installations/{installation_id}/access_tokens"
        
        try:
            response = httpx.post(url, headers=headers)
            response.raise_for_status()
            
            data = response.json()
            token = data["token"]
            # Token 有效期 1 小时
            expiry = time.time() + 3600
            
            self._installation_tokens[installation_id] = (token, expiry)
            
            logger.info(
                "github.token_fetched",
                installation_id=installation_id,
                expires_at=int(expiry)
            )
            
            return token
            
        except httpx.HTTPStatusError as e:
            if e.response.status_code == 401:
                raise GitHubAuthError(
                    "Invalid GitHub App credentials",
                    details={
                        "status_code": e.response.status_code,
                        "response": e.response.text
                    }
                )
            elif e.response.status_code == 404:
                raise GitHubAuthError(
                    f"Installation not found: {installation_id}",
                    details={"installation_id": installation_id}
                )
            else:
                raise GitHubAuthError(
                    f"Failed to get installation token: {e}",
                    details={
                        "status_code": e.response.status_code,
                        "response": e.response.text
                    }
                )
        except httpx.RequestError as e:
            raise GitHubAuthError(
                f"Network error while fetching token: {e}",
                details={"error_type": type(e).__name__}
            )
    
    def invalidate_token(self, installation_id: Optional[str] = None) -> None:
        """
        使缓存的 Token 失效
        
        Args:
            installation_id: 要失效的 Installation ID，None 表示全部失效
        """
        if installation_id is None:
            count = len(self._installation_tokens)
            self._installation_tokens.clear()
            logger.info("github.all_tokens_invalidated", count=count)
        else:
            installation_id = str(installation_id)
            if installation_id in self._installation_tokens:
                del self._installation_tokens[installation_id]
                logger.info(
                    "github.token_invalidated",
                    installation_id=installation_id
                )
    
    def get_cached_installations(self) -> list:
        """
        获取已缓存的 Installation ID 列表
        
        Returns:
            Installation ID 列表
        """
        return list(self._installation_tokens.keys())
    
    def is_token_valid(self, installation_id: str) -> bool:
        """
        检查指定 Installation 的 Token 是否有效
        
        Args:
            installation_id: Installation ID
        
        Returns:
            是否有效
        """
        installation_id = str(installation_id)
        
        if installation_id not in self._installation_tokens:
            return False
        
        _, expiry = self._installation_tokens[installation_id]
        return time.time() < expiry
