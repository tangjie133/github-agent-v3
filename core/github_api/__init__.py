"""
GitHub API Module

GitHub API 客户端，支持 PAT 和 GitHub App 认证
"""

from core.github_api.client import (
    GitHubClient,
    GitHubCredentials,
    get_github_client
)
from core.github_api.auth import GitHubAuthManager

__all__ = [
    'GitHubClient',
    'GitHubCredentials',
    'GitHubAuthManager',
    'get_github_client',
]