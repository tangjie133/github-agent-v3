"""
Git 操作封装

提供异步 Git 操作接口
"""

import asyncio
import os
import shutil
import tempfile
from pathlib import Path
from typing import Optional, List, Dict, Any
from dataclasses import dataclass

from core.logging import get_logger, traced
from core.config import get_config

logger = get_logger(__name__)


@dataclass
class CloneResult:
    """克隆结果"""
    success: bool
    path: Optional[Path] = None
    size_mb: float = 0.0
    is_shallow: bool = False
    error: Optional[str] = None


@dataclass
class CommitResult:
    """提交结果"""
    success: bool
    commit_sha: Optional[str] = None
    error: Optional[str] = None


class GitOperations:
    """
    Git 操作类
    
    封装所有 Git 命令执行
    """
    
    def __init__(self, working_dir: Optional[Path] = None):
        self.config = get_config()
        self.working_dir = working_dir or Path(tempfile.gettempdir()) / "github-agent-repos"
        self.working_dir.mkdir(parents=True, exist_ok=True)
    
    async def _run_git(self, args: List[str], cwd: Optional[Path] = None,
                      timeout: int = 300) -> tuple:
        """
        运行 Git 命令
        
        Returns:
            (returncode, stdout, stderr)
        """
        cmd = ["git"] + args
        
        logger.debug("git.run", cmd=" ".join(cmd), cwd=str(cwd))
        
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=cwd
            )
            
            stdout, stderr = await asyncio.wait_for(
                proc.communicate(),
                timeout=timeout
            )
            
            return (
                proc.returncode,
                stdout.decode('utf-8', errors='replace'),
                stderr.decode('utf-8', errors='replace')
            )
            
        except asyncio.TimeoutError:
            logger.error("git.timeout", cmd=" ".join(cmd))
            return (-1, "", "Timeout")
        except Exception as e:
            logger.error("git.error", cmd=" ".join(cmd), error=str(e))
            return (-1, "", str(e))
    
    @traced("git.clone")
    async def clone(self,
                   repo_url: str,
                   repo_name: str,
                   branch: str = "main",
                   shallow: bool = False) -> CloneResult:
        """
        克隆仓库
        
        Args:
            repo_url: 仓库 URL (https 或 ssh)
            repo_name: 本地目录名
            branch: 分支名
            shallow: 是否浅克隆
        
        Returns:
            克隆结果
        """
        target_path = self.working_dir / repo_name
        
        # 如果已存在，先删除
        if target_path.exists():
            logger.info("git.remove_existing", path=str(target_path))
            shutil.rmtree(target_path)
        
        args = ["clone"]
        
        if shallow:
            args.extend(["--depth", "1", "--single-branch", "--branch", branch])
        
        args.extend([repo_url, str(target_path)])
        
        logger.info("git.clone_start",
                   repo=repo_url,
                   shallow=shallow,
                   target=str(target_path))
        
        returncode, stdout, stderr = await self._run_git(args, timeout=300)
        
        if returncode != 0:
            logger.error("git.clone_failed",
                        repo=repo_url,
                        error=stderr)
            return CloneResult(
                success=False,
                error=stderr
            )
        
        # 计算大小
        try:
            size_bytes = sum(
                f.stat().st_size 
                for f in target_path.rglob('*') 
                if f.is_file()
            )
            size_mb = size_bytes / (1024 * 1024)
        except Exception:
            size_mb = 0
        
        logger.info("git.clone_complete",
                   repo=repo_url,
                   path=str(target_path),
                   size_mb=round(size_mb, 2))
        
        return CloneResult(
            success=True,
            path=target_path,
            size_mb=size_mb,
            is_shallow=shallow
        )
    
    @traced("git.create_branch")
    async def create_branch(self,
                           repo_path: Path,
                           branch_name: str,
                           base_branch: str = "main") -> bool:
        """
        创建并切换到新分支
        """
        # 先获取最新代码
        await self._run_git(["fetch", "origin"], cwd=repo_path)
        
        # 切换到基础分支
        await self._run_git(["checkout", base_branch], cwd=repo_path)
        await self._run_git(["pull", "origin", base_branch], cwd=repo_path)
        
        # 创建新分支
        returncode, _, stderr = await self._run_git(
            ["checkout", "-b", branch_name],
            cwd=repo_path
        )
        
        if returncode != 0:
            logger.error("git.branch_failed",
                        branch=branch_name,
                        error=stderr)
            return False
        
        logger.info("git.branch_created",
                   branch=branch_name,
                   base=base_branch)
        return True
    
    @traced("git.commit")
    async def commit_changes(self,
                            repo_path: Path,
                            message: str,
                            files: Optional[List[str]] = None) -> CommitResult:
        """
        提交更改
        
        Args:
            repo_path: 仓库路径
            message: 提交信息
            files: 要提交的文件列表（None=全部）
        """
        # 配置 git 用户（如果不存在）
        await self._run_git(["config", "user.email", "github-agent@local"], cwd=repo_path)
        await self._run_git(["config", "user.name", "GitHub Agent"], cwd=repo_path)
        
        # 添加文件
        if files:
            for f in files:
                await self._run_git(["add", f], cwd=repo_path)
        else:
            await self._run_git(["add", "-A"], cwd=repo_path)
        
        # 提交
        returncode, stdout, stderr = await self._run_git(
            ["commit", "-m", message],
            cwd=repo_path
        )
        
        if returncode != 0:
            # 可能是没有更改
            if "nothing to commit" in stderr.lower():
                logger.info("git.nothing_to_commit")
                return CommitResult(success=True, commit_sha=None)
            
            logger.error("git.commit_failed", error=stderr)
            return CommitResult(success=False, error=stderr)
        
        # 获取 commit SHA
        _, sha, _ = await self._run_git(
            ["rev-parse", "HEAD"],
            cwd=repo_path
        )
        sha = sha.strip()
        
        logger.info("git.committed",
                   message=message[:50],
                   sha=sha[:8])
        
        return CommitResult(success=True, commit_sha=sha)
    
    @traced("git.push")
    async def push(self,
                  repo_path: Path,
                  branch: str,
                  remote: str = "origin") -> bool:
        """
        推送到远程
        """
        # 添加 token 支持（如果需要）
        # 这里简化处理，假设已经配置了认证
        
        returncode, _, stderr = await self._run_git(
            ["push", "-u", remote, branch],
            cwd=repo_path
        )
        
        if returncode != 0:
            logger.error("git.push_failed",
                        branch=branch,
                        error=stderr)
            return False
        
        logger.info("git.pushed", branch=branch)
        return True
    
    async def apply_patch(self, repo_path: Path, 
                         patch_content: str) -> bool:
        """
        应用补丁
        """
        # 使用 git apply
        proc = await asyncio.create_subprocess_exec(
            "git", "apply", "--check",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_path
        )
        
        stdout, stderr = await proc.communicate(patch_content.encode())
        
        if proc.returncode != 0:
            logger.error("git.patch_check_failed", error=stderr.decode())
            return False
        
        # 应用补丁
        proc = await asyncio.create_subprocess_exec(
            "git", "apply",
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=repo_path
        )
        
        stdout, stderr = await proc.communicate(patch_content.encode())
        
        if proc.returncode != 0:
            logger.error("git.patch_apply_failed", error=stderr.decode())
            return False
        
        logger.info("git.patch_applied")
        return True
    
    async def write_file(self, repo_path: Path, file_path: str, 
                        content: str) -> bool:
        """
        写入文件内容
        """
        full_path = repo_path / file_path
        
        try:
            full_path.parent.mkdir(parents=True, exist_ok=True)
            full_path.write_text(content, encoding='utf-8')
            return True
        except Exception as e:
            logger.error("git.write_file_failed",
                        path=file_path,
                        error=str(e))
            return False
    
    async def delete_file(self, repo_path: Path, file_path: str) -> bool:
        """
        删除文件
        """
        full_path = repo_path / file_path
        
        try:
            if full_path.exists():
                full_path.unlink()
            return True
        except Exception as e:
            logger.error("git.delete_file_failed",
                        path=file_path,
                        error=str(e))
            return False
    
    async def cleanup(self, repo_path: Path):
        """
        清理仓库目录
        """
        try:
            if repo_path.exists():
                shutil.rmtree(repo_path)
                logger.info("git.cleanup", path=str(repo_path))
        except Exception as e:
            logger.error("git.cleanup_failed",
                        path=str(repo_path),
                        error=str(e))
    
    async def get_file_content(self, repo_path: Path, 
                               file_path: str) -> Optional[str]:
        """
        获取文件内容
        """
        full_path = repo_path / file_path
        
        try:
            return full_path.read_text(encoding='utf-8')
        except Exception as e:
            logger.error("git.read_file_failed",
                        path=file_path,
                        error=str(e))
            return None
    
    async def list_files(self, repo_path: Path, 
                        pattern: str = "*.py") -> List[str]:
        """
        列出匹配的文件
        """
        files = []
        for f in repo_path.rglob(pattern):
            if f.is_file():
                files.append(str(f.relative_to(repo_path)))
        return files


# 全局实例
_git_ops: Optional[GitOperations] = None


def get_git_operations() -> GitOperations:
    """获取 GitOperations 实例"""
    global _git_ops
    if _git_ops is None:
        _git_ops = GitOperations()
    return _git_ops