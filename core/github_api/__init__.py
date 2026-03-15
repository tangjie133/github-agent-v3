"""
GitHub API Module

GitHub API 客户端，支持 PAT 和 GitHub App 认证
"""

from core.github_api.client import (
    GitHubClient,
    GitHubCredentials,
    GitHubAppAuth,
    get_github_client
)

__all__ = [
    'GitHubClient',
    'GitHubCredentials',
    'GitHubAppAuth',
    'get_github_client',
]