"""
统一存储管理器
集中管理所有数据、日志、缓存的存储位置
"""

import os
import json
import gzip
import time
import shutil
from pathlib import Path
from typing import Dict, Optional, Any
from dataclasses import dataclass
from core.logging import get_logger

logger = get_logger(__name__)


@dataclass
class DiskUsage:
    """磁盘使用情况"""
    repos: int
    vector_indices: int
    logs: int
    webhooks: int
    cache: int
    total: int
    
    def to_dict(self) -> Dict[str, str]:
        return {
            'repos': self._format_size(self.repos),
            'vector_indices': self._format_size(self.vector_indices),
            'logs': self._format_size(self.logs),
            'webhooks': self._format_size(self.webhooks),
            'cache': self._format_size(self.cache),
            'total': self._format_size(self.total),
        }
    
    @staticmethod
    def _format_size(bytes_val: int) -> str:
        for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
            if bytes_val < 1024:
                return f"{bytes_val:.1f} {unit}"
            bytes_val /= 1024
        return f"{bytes_val:.1f} PB"


class StorageManager:
    """
    统一存储管理器
    
    目录结构：
    ${GITHUB_AGENT_DATADIR}/
        config/           # 配置文件
        data/             # 应用数据
            repos/        # 克隆的代码库
            vector_indices/  # 向量索引
            cache/        # 运行时缓存
            state/        # 状态数据（SQLite）
        logs/             # 日志文件
            agent/        # 主应用日志
            workers/      # Worker日志
            webhook/      # Webhook日志
        webhooks/         # Webhook事件存档
        backups/          # 自动备份
        tmp/              # 临时文件
    """
    
    def __init__(self, base_dir: Optional[Path] = None):
        self.base = Path(base_dir or os.getenv(
            'GITHUB_AGENT_DATADIR',
            Path.home() / 'github-agent-data'
        ))
        self._ensure_structure()
    
    def _ensure_structure(self):
        """创建标准目录结构"""
        dirs = [
            'config',
            'data/repos',
            'data/vector_indices',
            'data/cache/http',
            'data/cache/llm_responses',
            'data/cache/repo_metadata',
            'data/state',
            'logs/agent',
            'logs/workers',
            'logs/webhook',
            'webhooks',
            'backups/daily',
            'tmp/downloads',
            'tmp/processing',
        ]
        
        for d in dirs:
            (self.base / d).mkdir(parents=True, exist_ok=True)
        
        # 创建 .gitignore 防止 tmp 被提交
        gitignore = self.base / 'tmp' / '.gitignore'
        if not gitignore.exists():
            gitignore.write_text('*\n')
        
        logger.debug(f"Storage structure ensured at {self.base}")
    
    # ========== 路径访问器 ==========
    
    @property
    def config_dir(self) -> Path:
        return self.base / 'config'
    
    @property
    def data_dir(self) -> Path:
        return self.base / 'data'
    
    @property
    def repos_dir(self) -> Path:
        return self.base / 'data/repos'
    
    def get_repo_path(self, owner: str, repo: str) -> Path:
        """获取代码库路径"""
        return self.repos_dir / owner / repo
    
    @property
    def vector_indices_dir(self) -> Path:
        return self.base / 'data/vector_indices'
    
    def get_vector_index_path(self, owner: str, repo: str) -> Path:
        """获取向量索引路径"""
        return self.vector_indices_dir / f"{owner}_{repo}"
    
    @property
    def cache_dir(self) -> Path:
        return self.base / 'data/cache'
    
    @property
    def state_dir(self) -> Path:
        return self.base / 'data/state'
    
    @property
    def state_db_path(self) -> Path:
        """状态数据库路径"""
        return self.state_dir / 'issue_states.db'
    
    @property
    def logs_dir(self) -> Path:
        return self.base / 'logs'
    
    def get_log_path(self, component: str, name: str = 'current') -> Path:
        """获取日志文件路径"""
        return self.logs_dir / component / f'{name}.log'
    
    @property
    def webhook_archive_dir(self) -> Path:
        """获取 webhook 存档目录（按日期）"""
        from datetime import datetime
        now = datetime.now()
        path = (
            self.base / 'webhooks' / 
            str(now.year) / 
            f'{now.month:02d}' / 
            f'{now.day:02d}'
        )
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    @property
    def backups_dir(self) -> Path:
        return self.base / 'backups'
    
    @property
    def tmp_dir(self) -> Path:
        return self.base / 'tmp'
    
    # ========== 操作 ==========
    
    def cleanup_tmp(self, max_age_hours: int = 24) -> int:
        """清理临时文件，返回清理数量"""
        count = 0
        cutoff = time.time() - (max_age_hours * 3600)
        
        for path in self.tmp_dir.rglob('*'):
            if path.is_file() and path.stat().st_mtime < cutoff:
                try:
                    path.unlink()
                    count += 1
                    logger.debug(f"Cleaned up temp file: {path}")
                except Exception as e:
                    logger.warning(f"Failed to cleanup {path}: {e}")
        
        if count > 0:
            logger.info(f"Cleaned up {count} temp files")
        
        return count
    
    def cleanup_old_logs(self, retention_days: int = 30) -> int:
        """清理旧日志文件"""
        count = 0
        cutoff = time.time() - (retention_days * 86400)
        
        for log_dir in [self.logs_dir / 'agent', self.logs_dir / 'workers']:
            if not log_dir.exists():
                continue
            for path in log_dir.glob('*.log.*'):
                if path.is_file() and path.stat().st_mtime < cutoff:
                    try:
                        path.unlink()
                        count += 1
                    except Exception as e:
                        logger.warning(f"Failed to remove old log {path}: {e}")
        
        return count
    
    def cleanup_old_webhooks(self, retention_days: int = 7) -> int:
        """清理旧 webhook 存档"""
        count = 0
        cutoff = time.time() - (retention_days * 86400)
        
        webhooks_dir = self.base / 'webhooks'
        if not webhooks_dir.exists():
            return 0
        
        for path in webhooks_dir.rglob('*.json'):
            if path.is_file() and path.stat().st_mtime < cutoff:
                try:
                    path.unlink()
                    count += 1
                except Exception as e:
                    logger.warning(f"Failed to remove old webhook {path}: {e}")
        
        # 清理空目录
        for path in sorted(webhooks_dir.rglob('*'), reverse=True):
            if path.is_dir() and not any(path.iterdir()):
                try:
                    path.rmdir()
                except Exception:
                    pass
        
        return count
    
    def backup(self, name: Optional[str] = None) -> Path:
        """创建备份"""
        from datetime import datetime
        
        backup_name = name or datetime.now().strftime('%Y-%m-%d-%H%M%S')
        backup_dir = self.backups_dir / 'daily' / backup_name
        backup_dir.mkdir(parents=True, exist_ok=True)
        
        # 备份状态数据库
        state_db = self.state_db_path
        if state_db.exists():
            with open(state_db, 'rb') as f_in:
                with gzip.open(backup_dir / 'state.db.gz', 'wb') as f_out:
                    f_out.write(f_in.read())
        
        # 备份配置
        config_file = self.config_dir / 'agent.yml'
        if config_file.exists():
            with open(config_file, 'rb') as f_in:
                with gzip.open(backup_dir / 'config.yml.gz', 'wb') as f_out:
                    f_out.write(f_in.read())
        
        # 写入备份元数据
        metadata = {
            'created_at': datetime.now().isoformat(),
            'version': '3.0.0',
            'contents': ['state.db', 'config.yml'],
        }
        (backup_dir / 'metadata.json').write_text(json.dumps(metadata, indent=2))
        
        logger.info(f"Backup created: {backup_dir}")
        return backup_dir
    
    def list_backups(self) -> list:
        """列出所有备份"""
        backups = []
        backups_dir = self.backups_dir / 'daily'
        
        if not backups_dir.exists():
            return backups
        
        for backup_dir in sorted(backups_dir.iterdir(), reverse=True):
            if backup_dir.is_dir():
                metadata_file = backup_dir / 'metadata.json'
                if metadata_file.exists():
                    metadata = json.loads(metadata_file.read_text())
                    backups.append({
                        'name': backup_dir.name,
                        'created_at': metadata.get('created_at'),
                        'path': str(backup_dir),
                    })
        
        return backups
    
    def restore_backup(self, name: str) -> bool:
        """从备份恢复"""
        backup_dir = self.backups_dir / 'daily' / name
        
        if not backup_dir.exists():
            logger.error(f"Backup not found: {name}")
            return False
        
        try:
            # 恢复状态数据库
            state_backup = backup_dir / 'state.db.gz'
            if state_backup.exists():
                with gzip.open(state_backup, 'rb') as f_in:
                    self.state_db_path.write_bytes(f_in.read())
            
            # 恢复配置
            config_backup = backup_dir / 'config.yml.gz'
            if config_backup.exists():
                with gzip.open(config_backup, 'rb') as f_in:
                    (self.config_dir / 'agent.yml').write_bytes(f_in.read())
            
            logger.info(f"Restored from backup: {name}")
            return True
            
        except Exception as e:
            logger.error(f"Failed to restore backup: {e}")
            return False
    
    def get_disk_usage(self) -> DiskUsage:
        """获取各目录磁盘使用情况"""
        return DiskUsage(
            repos=self._dir_size(self.repos_dir),
            vector_indices=self._dir_size(self.vector_indices_dir),
            logs=self._dir_size(self.logs_dir),
            webhooks=self._dir_size(self.base / 'webhooks'),
            cache=self._dir_size(self.cache_dir),
            total=self._dir_size(self.base),
        )
    
    def _dir_size(self, path: Path) -> int:
        """计算目录大小（字节）"""
        if not path.exists():
            return 0
        
        total = 0
        try:
            for entry in path.rglob('*'):
                if entry.is_file():
                    total += entry.stat().st_size
        except Exception as e:
            logger.warning(f"Failed to calculate size of {path}: {e}")
        
        return total


# 全局单例
_storage_instance: Optional[StorageManager] = None


def get_storage(base_dir: Optional[Path] = None) -> StorageManager:
    """获取 StorageManager 单例
    
    优先顺序：
    1. 传入的 base_dir 参数
    2. 配置系统中的 storage.datadir
    3. 环境变量 GITHUB_AGENT_DATADIR
    4. 默认值 ~/github-agent-data
    """
    global _storage_instance
    
    if base_dir is not None:
        return StorageManager(base_dir)
    
    if _storage_instance is None:
        # 从配置系统获取数据目录
        try:
            from core.config import get_config
            config = get_config()
            datadir = config.storage.datadir
            _storage_instance = StorageManager(datadir)
        except Exception:
            # 配置系统未初始化，回退到环境变量/默认值
            _storage_instance = StorageManager()
    
    return _storage_instance
