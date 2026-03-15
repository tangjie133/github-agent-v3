#!/usr/bin/env python3
"""
知识库同步管理器 (Knowledge Sync Manager)

负责：
1. 将本地成功案例推送到资料仓库
2. 管理同步队列和失败重试
3. 新环境初始化时拉取知识库
4. 处理版本冲突

Phase 2 实现
"""

import os
import json
import time
import logging
import hashlib
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


@dataclass
class SyncStatus:
    """同步状态"""
    case_id: str
    status: str  # pending, syncing, success, failed
    attempts: int = 0
    last_attempt: Optional[str] = None
    error_message: Optional[str] = None
    remote_url: Optional[str] = None


class KnowledgeSyncManager:
    """
    知识库同步管理器
    
    管理本地知识库与远程资料仓库的同步
    """
    
    def __init__(self,
                 knowledge_repo_url: str,
                 local_kb_path: Path,
                 github_token: str = None,
                 sync_interval: int = 1800):  # 默认30分钟
        """
        初始化同步管理器
        
        Args:
            knowledge_repo_url: 资料仓库 URL (如 https://github.com/owner/knowledge-base)
            local_kb_path: 本地知识库路径
            github_token: GitHub Token，用于认证
            sync_interval: 自动同步间隔（秒）
        """
        self.knowledge_repo_url = knowledge_repo_url
        self.local_kb_path = Path(local_kb_path)
        self.github_token = github_token or os.environ.get("GITHUB_TOKEN")
        self.sync_interval = sync_interval
        
        # 待同步队列
        self.pending_queue: List[str] = []
        self.sync_status: Dict[str, SyncStatus] = {}
        
        # 本地缓存路径
        self.sync_state_path = self.local_kb_path / ".sync_state.json"
        self.temp_repo_path = self.local_kb_path / ".temp_knowledge_repo"
        
        # 加载同步状态
        self._load_sync_state()
        
        # 初始化日志改为 debug 级别
        logger.debug(f"[KnowledgeSync] 初始化完成")
        logger.debug(f"[KnowledgeSync]   资料仓库: {knowledge_repo_url}")
        logger.debug(f"[KnowledgeSync]   本地路径: {local_kb_path}")
        logger.debug(f"[KnowledgeSync]   同步间隔: {sync_interval}秒")
    
    # ============================================================================
    # 核心同步方法
    # ============================================================================
    
    def sync_case(self, case_id: str, force: bool = False) -> bool:
        """
        同步单个案例到资料仓库
        
        Args:
            case_id: 案例ID
            force: 强制同步（即使已同步过）
            
        Returns:
            是否成功
        """
        logger.info(f"[KnowledgeSync] 同步案例: {case_id}")
        
        # 检查是否已同步且未强制
        if not force and self._is_synced(case_id):
            logger.debug(f"[KnowledgeSync]   案例已同步，跳过")
            return True
        
        # 更新状态
        status = SyncStatus(
            case_id=case_id,
            status="syncing",
            attempts=self.sync_status.get(case_id, SyncStatus(case_id, "")).attempts + 1,
            last_attempt=datetime.now().isoformat()
        )
        self.sync_status[case_id] = status
        
        try:
            # 1. 加载案例
            case_file = self._find_case_file(case_id)
            if not case_file:
                raise FileNotFoundError(f"案例文件不存在: {case_id}")
            
            with open(case_file, 'r', encoding='utf-8') as f:
                case_data = json.load(f)
            
            logger.debug(f"[KnowledgeSync]   案例文件: {case_file}")
            
            # 2. 推送到资料仓库
            remote_path = self._push_to_remote(case_data, case_file)
            
            # 3. 更新状态
            status.status = "success"
            status.remote_url = remote_path
            self.sync_status[case_id] = status
            self._save_sync_state()
            
            logger.info(f"[KnowledgeSync] ✅ 案例同步成功: {case_id}")
            logger.info(f"[KnowledgeSync]    远程路径: {remote_path}")
            return True
            
        except Exception as e:
            # 更新失败状态
            status.status = "failed"
            status.error_message = str(e)
            self.sync_status[case_id] = status
            self._save_sync_state()
            
            logger.error(f"[KnowledgeSync] ❌ 案例同步失败: {case_id}")
            logger.error(f"[KnowledgeSync]    错误: {e}")
            
            # 添加到待同步队列（用于重试）
            if case_id not in self.pending_queue:
                self.pending_queue.append(case_id)
            
            return False
    
    def sync_all_pending(self) -> Tuple[int, int]:
        """
        同步所有待处理案例
        
        Returns:
            (成功数, 失败数)
        """
        logger.info(f"[KnowledgeSync] 开始批量同步，待处理: {len(self.pending_queue)} 个")
        
        success_count = 0
        failed_count = 0
        still_pending = []
        
        for case_id in self.pending_queue[:]:
            # 检查重试次数
            status = self.sync_status.get(case_id, SyncStatus(case_id, ""))
            if status.attempts >= 3:
                logger.warning(f"[KnowledgeSync]   案例 {case_id} 已达到最大重试次数，跳过")
                failed_count += 1
                continue
            
            # 执行同步
            if self.sync_case(case_id):
                success_count += 1
            else:
                still_pending.append(case_id)
                failed_count += 1
            
            # 避免过于频繁
            time.sleep(1)
        
        # 更新待处理队列（保留失败的）
        self.pending_queue = still_pending
        self._save_sync_state()
        
        logger.info(f"[KnowledgeSync] 批量同步完成: 成功 {success_count}, 失败 {failed_count}")
        return success_count, failed_count
    
    def pull_from_remote(self, sync_mode: str = "full") -> bool:
        """
        从资料仓库拉取知识库
        
        Args:
            sync_mode: 
                - "full": 拉取全部
                - "recent": 只拉取最近30天
                - "minimal": 只拉取模式库
                
        Returns:
            是否成功
        """
        logger.info(f"[KnowledgeSync] 从远程拉取知识库 (模式: {sync_mode})")
        
        try:
            # 1. 克隆/拉取资料仓库
            repo_path = self._ensure_knowledge_repo()
            
            # 2. 根据模式导入
            if sync_mode == "full":
                self._import_all_cases(repo_path)
            elif sync_mode == "recent":
                self._import_recent_cases(repo_path, days=30)
            elif sync_mode == "minimal":
                self._import_patterns_only(repo_path)
            
            logger.info(f"[KnowledgeSync] ✅ 拉取完成")
            return True
            
        except Exception as e:
            logger.error(f"[KnowledgeSync] ❌ 拉取失败: {e}")
            return False
    
    def initialize_new_environment(self, 
                                   sync_mode: str = "full",
                                   knowledge_repo_url: str = None) -> bool:
        """
        初始化新环境（首次部署使用）
        
        Args:
            sync_mode: 同步模式
            knowledge_repo_url: 可选的新知识库URL
            
        Returns:
            是否成功
        """
        if knowledge_repo_url:
            self.knowledge_repo_url = knowledge_repo_url
        
        logger.info(f"[KnowledgeSync] 初始化新环境")
        logger.info(f"[KnowledgeSync]   知识库: {self.knowledge_repo_url}")
        logger.info(f"[KnowledgeSync]   模式: {sync_mode}")
        
        # 创建本地目录
        self.local_kb_path.mkdir(parents=True, exist_ok=True)
        
        # 从远程拉取
        return self.pull_from_remote(sync_mode)
    
    # ============================================================================
    # 推送实现
    # ============================================================================
    
    def _push_to_remote(self, case_data: Dict, local_file: Path) -> str:
        """
        推送到远程资料仓库
        
        使用 GitHub API 直接提交文件
        
        Args:
            case_data: 案例数据
            local_file: 本地文件路径
            
        Returns:
            远程文件路径
        """
        # 解析仓库信息
        repo_owner, repo_name = self._parse_repo_url(self.knowledge_repo_url)
        
        # 生成远程文件路径
        case_id = case_data.get("case_id", "unknown")
        created_at = case_data.get("created_at", datetime.now().isoformat())
        date = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
        
        remote_path = f"cases/{date.year}/{date.month:02d}/{case_id}.json"
        
        logger.debug(f"[KnowledgeSync]   推送到: {repo_owner}/{repo_name}/{remote_path}")
        
        # 使用 GitHub API 提交文件
        try:
            import requests
            
            # GitHub API URL
            api_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/contents/{remote_path}"
            
            # 读取文件内容并转为 base64
            import base64
            with open(local_file, 'rb') as f:
                content = base64.b64encode(f.read()).decode('utf-8')
            
            # 检查文件是否已存在
            existing_sha = self._get_file_sha(repo_owner, repo_name, remote_path)
            
            # 准备请求数据
            commit_message = f"Add case: {case_data.get('issue', {}).get('title', case_id)}"
            data = {
                "message": commit_message,
                "content": content,
                "branch": "main"
            }
            if existing_sha:
                data["sha"] = existing_sha
                commit_message = f"Update case: {case_data.get('issue', {}).get('title', case_id)}"
                data["message"] = commit_message
            
            # 发送请求
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.put(api_url, headers=headers, json=data, timeout=30)
            
            if response.status_code in [200, 201]:
                result = response.json()
                remote_url = result.get("content", {}).get("html_url", "")
                logger.debug(f"[KnowledgeSync]   提交成功: {commit_message}")
                return remote_url
            else:
                raise Exception(f"GitHub API 错误: {response.status_code} - {response.text}")
                
        except ImportError:
            logger.error("requests 库未安装")
            raise
        except Exception as e:
            logger.error(f"推送失败: {e}")
            raise
    
    def _get_file_sha(self, owner: str, repo: str, path: str) -> Optional[str]:
        """获取文件的 SHA（用于更新）"""
        try:
            import requests
            
            api_url = f"https://api.github.com/repos/{owner}/{repo}/contents/{path}"
            headers = {
                "Authorization": f"token {self.github_token}",
                "Accept": "application/vnd.github.v3+json"
            }
            
            response = requests.get(api_url, headers=headers, timeout=10)
            
            if response.status_code == 200:
                return response.json().get("sha")
            return None
            
        except Exception as e:
            logger.debug(f"获取文件 SHA 失败: {e}")
            return None
    
    # ============================================================================
    # 拉取实现
    # ============================================================================
    
    def _ensure_knowledge_repo(self) -> Path:
        """确保资料仓库可用，返回本地路径"""
        if not self.github_token:
            raise ValueError("GitHub Token 未配置")
        
        # 清理旧目录
        if self.temp_repo_path.exists():
            import shutil
            shutil.rmtree(self.temp_repo_path)
        
        # 克隆仓库
        auth_url = self.knowledge_repo_url.replace(
            "https://github.com/",
            f"https://x-access-token:{self.github_token}@github.com/"
        )
        
        logger.debug(f"[KnowledgeSync]   克隆资料仓库...")
        
        import subprocess
        result = subprocess.run(
            ["git", "clone", "--depth", "1", auth_url, str(self.temp_repo_path)],
            capture_output=True,
            text=True,
            timeout=60
        )
        
        if result.returncode != 0:
            raise Exception(f"克隆失败: {result.stderr}")
        
        return self.temp_repo_path
    
    def _import_all_cases(self, repo_path: Path) -> int:
        """导入所有案例"""
        cases_dir = repo_path / "cases"
        if not cases_dir.exists():
            logger.warning("[KnowledgeSync]   远程没有 cases 目录")
            return 0
        
        imported = 0
        for case_file in cases_dir.rglob("case_*.json"):
            try:
                # 复制到本地
                relative_path = case_file.relative_to(repo_path)
                local_file = self.local_kb_path / relative_path
                local_file.parent.mkdir(parents=True, exist_ok=True)
                
                import shutil
                shutil.copy2(case_file, local_file)
                
                imported += 1
                logger.debug(f"[KnowledgeSync]   导入: {relative_path}")
                
            except Exception as e:
                logger.warning(f"[KnowledgeSync]   导入失败 {case_file}: {e}")
        
        logger.info(f"[KnowledgeSync]   导入 {imported} 个案例")
        return imported
    
    def _import_recent_cases(self, repo_path: Path, days: int = 30) -> int:
        """只导入最近的案例"""
        from datetime import timedelta
        
        cutoff_date = datetime.now() - timedelta(days=days)
        
        cases_dir = repo_path / "cases"
        if not cases_dir.exists():
            return 0
        
        imported = 0
        for case_file in cases_dir.rglob("case_*.json"):
            try:
                # 检查创建时间
                with open(case_file) as f:
                    data = json.load(f)
                
                created = datetime.fromisoformat(
                    data.get("created_at", "1970-01-01").replace('Z', '+00:00')
                )
                
                if created >= cutoff_date:
                    relative_path = case_file.relative_to(repo_path)
                    local_file = self.local_kb_path / relative_path
                    local_file.parent.mkdir(parents=True, exist_ok=True)
                    
                    import shutil
                    shutil.copy2(case_file, local_file)
                    imported += 1
                    
            except Exception as e:
                logger.warning(f"导入失败 {case_file}: {e}")
        
        logger.info(f"[KnowledgeSync]   导入 {imported} 个最近案例")
        return imported
    
    def _import_patterns_only(self, repo_path: Path) -> int:
        """只导入模式库"""
        patterns_dir = repo_path / "patterns"
        if not patterns_dir.exists():
            logger.warning("[KnowledgeSync]   远程没有 patterns 目录")
            return 0
        
        imported = 0
        for pattern_file in patterns_dir.rglob("*.json"):
            try:
                relative_path = pattern_file.relative_to(repo_path)
                local_file = self.local_kb_path / relative_path
                local_file.parent.mkdir(parents=True, exist_ok=True)
                
                import shutil
                shutil.copy2(pattern_file, local_file)
                imported += 1
                
            except Exception as e:
                logger.warning(f"导入失败 {pattern_file}: {e}")
        
        logger.info(f"[KnowledgeSync]   导入 {imported} 个模式")
        return imported
    
    # ============================================================================
    # 辅助方法
    # ============================================================================
    
    def _parse_repo_url(self, url: str) -> Tuple[str, str]:
        """解析仓库 URL，返回 (owner, repo)"""
        # 处理 HTTPS 和 SSH 格式
        if url.startswith("https://github.com/"):
            parts = url.replace("https://github.com/", "").split("/")
        elif url.startswith("git@github.com:"):
            parts = url.replace("git@github.com:", "").replace(".git", "").split("/")
        else:
            raise ValueError(f"不支持的仓库 URL 格式: {url}")
        
        if len(parts) < 2:
            raise ValueError(f"无法解析仓库 URL: {url}")
        
        return parts[0], parts[1]
    
    def _find_case_file(self, case_id: str) -> Optional[Path]:
        """查找案例文件"""
        cases_dir = self.local_kb_path / "cases"
        if not cases_dir.exists():
            return None
        
        for case_file in cases_dir.rglob(f"{case_id}.json"):
            return case_file
        
        return None
    
    def _is_synced(self, case_id: str) -> bool:
        """检查案例是否已同步"""
        status = self.sync_status.get(case_id)
        return status is not None and status.status == "success"
    
    def _load_sync_state(self):
        """加载同步状态"""
        if self.sync_state_path.exists():
            try:
                with open(self.sync_state_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                
                self.pending_queue = data.get("pending_queue", [])
                self.sync_status = {
                    k: SyncStatus(**v) 
                    for k, v in data.get("sync_status", {}).items()
                }
                
                logger.debug(f"[KnowledgeSync] 加载同步状态: {len(self.pending_queue)} 个待处理")
                
            except Exception as e:
                logger.warning(f"[KnowledgeSync] 加载同步状态失败: {e}")
    
    def _save_sync_state(self):
        """保存同步状态"""
        try:
            data = {
                "pending_queue": self.pending_queue,
                "sync_status": {
                    k: {
                        "case_id": v.case_id,
                        "status": v.status,
                        "attempts": v.attempts,
                        "last_attempt": v.last_attempt,
                        "error_message": v.error_message,
                        "remote_url": v.remote_url
                    }
                    for k, v in self.sync_status.items()
                },
                "last_saved": datetime.now().isoformat()
            }
            
            with open(self.sync_state_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.warning(f"[KnowledgeSync] 保存同步状态失败: {e}")
    
    def get_sync_summary(self) -> Dict:
        """获取同步摘要"""
        return {
            "pending_count": len(self.pending_queue),
            "synced_count": sum(1 for s in self.sync_status.values() if s.status == "success"),
            "failed_count": sum(1 for s in self.sync_status.values() if s.status == "failed"),
            "knowledge_repo": self.knowledge_repo_url,
            "last_update": datetime.now().isoformat()
        }


# ================================================================================
# 便捷函数
# ================================================================================

def create_sync_manager(knowledge_repo_url: str = None,
                       local_kb_path: Path = None,
                       github_token: str = None) -> Optional[KnowledgeSyncManager]:
    """创建同步管理器实例
    
    配置优先级：
    1. 传入的参数
    2. KNOWLEDGE_REPO_URL 环境变量
    3. KB_REPO 环境变量（与拉取功能共用）
    
    如果未配置仓库 URL，返回 None（禁用同步）
    """
    
    # 从环境变量获取配置（支持多种配置名）
    knowledge_repo_url = (
        knowledge_repo_url or 
        os.environ.get("KNOWLEDGE_REPO_URL") or
        os.environ.get("KB_REPO")
    )
    
    if not local_kb_path:
        local_kb_path = Path(__file__).parent / "data" / "cases"
    
    # 未配置仓库 URL，返回 None（不报错，允许禁用）
    if not knowledge_repo_url:
        logger.debug("[KnowledgeSync] 未配置知识库仓库 URL，同步功能禁用")
        return None
    
    # 确保 URL 格式正确
    if not knowledge_repo_url.startswith(("http://", "https://", "git@")):
        # 可能是简写格式 owner/repo，转为完整 URL
        if "/" in knowledge_repo_url and "github.com" not in knowledge_repo_url:
            knowledge_repo_url = f"https://github.com/{knowledge_repo_url}"
    
    # 获取 GitHub Token
    github_token = (
        github_token or
        os.environ.get("GITHUB_TOKEN") or
        os.environ.get("KB_GITHUB_TOKEN")
    )
    
    if not github_token:
        logger.warning("[KnowledgeSync] 未配置 GITHUB_TOKEN，同步功能受限")
    
    return KnowledgeSyncManager(
        knowledge_repo_url=knowledge_repo_url,
        local_kb_path=local_kb_path,
        github_token=github_token
    )


if __name__ == "__main__":
    # 简单测试
    import tempfile
    
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试案例
        cases_dir = Path(tmpdir) / "cases" / "2026" / "03"
        cases_dir.mkdir(parents=True)
        
        test_case = {
            "case_id": "case_20260312_test001",
            "created_at": datetime.now().isoformat(),
            "repository": "test/repo",
            "issue": {"title": "Test Issue", "body": "Test"},
            "solution": {"description": "Test fix"},
            "outcome": {"success": True}
        }
        
        with open(cases_dir / "case_20260312_test001.json", 'w') as f:
            json.dump(test_case, f, indent=2)
        
        # 创建同步管理器（无实际推送）
        manager = KnowledgeSyncManager(
            knowledge_repo_url="https://github.com/test/knowledge-base",
            local_kb_path=Path(tmpdir),
            github_token="fake_token_for_test"
        )
        
        print(f"同步摘要: {manager.get_sync_summary()}")
