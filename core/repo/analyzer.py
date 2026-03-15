"""
代码库分析器
下载并分析 GitHub 仓库，提取有用信息用于回答
"""

import os
import re
import subprocess
import tempfile
from core.logging import get_logger
from pathlib import Path
from typing import Dict, List, Optional, Any
from dataclasses import dataclass

logger = get_logger(__name__)


@dataclass
class RepoAnalysis:
    """代码库分析结果"""
    repo_full_name: str
    readme_content: str = ""
    main_files: List[str] = None
    code_structure: Dict[str, Any] = None
    key_functions: List[str] = None
    examples: List[str] = None
    
    def __post_init__(self):
        if self.main_files is None:
            self.main_files = []
        if self.code_structure is None:
            self.code_structure = {}
        if self.key_functions is None:
            self.key_functions = []
        if self.examples is None:
            self.examples = []


class RepoAnalyzer:
    """代码库分析器"""
    
    def __init__(self, work_dir: str = None):
        self.work_dir = work_dir or os.environ.get(
            'GITHUB_AGENT_WORKDIR', '/tmp/github-agent-repos'
        )
        Path(self.work_dir).mkdir(parents=True, exist_ok=True)
    
    def analyze_repo(self, repo_full_name: str, github_token: str = None) -> RepoAnalysis:
        """
        分析代码库
        
        Args:
            repo_full_name: 仓库全名，如 "owner/repo"
            github_token: GitHub Token（用于私有仓库）
            
        Returns:
            RepoAnalysis 分析结果
        """
        result = RepoAnalysis(repo_full_name=repo_full_name)
        
        # 1. 克隆仓库
        repo_path = self._clone_repo(repo_full_name, github_token)
        if not repo_path:
            logger.error(f"Failed to clone repo: {repo_full_name}")
            return result
        
        try:
            # 2. 读取 README
            result.readme_content = self._extract_readme(repo_path)
            
            # 3. 分析代码结构
            result.code_structure = self._analyze_structure(repo_path)
            
            # 4. 提取关键文件
            result.main_files = self._find_main_files(repo_path)
            
            # 5. 提取关键函数/类
            result.key_functions = self._extract_key_functions(repo_path)
            
            # 6. 查找示例代码
            result.examples = self._find_examples(repo_path)
            
        finally:
            # 清理临时文件（可选，可以保留缓存）
            # self._cleanup(repo_path)
            pass
        
        return result
    
    def _clone_repo(self, repo_full_name: str, github_token: str = None) -> Optional[str]:
        """克隆仓库到本地"""
        repo_dir = Path(self.work_dir) / repo_full_name.replace('/', '_')
        
        # 如果已存在，先删除（或拉取更新）
        if repo_dir.exists():
            logger.debug(f"Repo already exists at {repo_dir}, pulling updates...")
            try:
                subprocess.run(
                    ['git', '-C', str(repo_dir), 'pull'],
                    capture_output=True,
                    timeout=30
                )
                return str(repo_dir)
            except Exception as e:
                logger.warning(f"Failed to pull updates: {e}, re-cloning...")
                import shutil
                shutil.rmtree(repo_dir)
        
        # 构建克隆 URL
        if github_token:
            clone_url = f"https://{github_token}@github.com/{repo_full_name}.git"
        else:
            clone_url = f"https://github.com/{repo_full_name}.git"
        
        logger.info(f"Cloning {repo_full_name}...")
        try:
            result = subprocess.run(
                ['git', 'clone', '--depth', '1', clone_url, str(repo_dir)],
                capture_output=True,
                text=True,
                timeout=120
            )
            if result.returncode == 0:
                logger.info(f"Successfully cloned to {repo_dir}")
                return str(repo_dir)
            else:
                logger.error(f"Clone failed: {result.stderr}")
                return None
        except subprocess.TimeoutExpired:
            logger.error("Clone timeout")
            return None
        except Exception as e:
            logger.error(f"Clone error: {e}")
            return None
    
    def _extract_readme(self, repo_path: str) -> str:
        """提取 README 内容"""
        readme_files = ['README.md', 'README.MD', 'readme.md', 'README']
        
        for readme_file in readme_files:
            readme_path = Path(repo_path) / readme_file
            if readme_path.exists():
                try:
                    content = readme_path.read_text(encoding='utf-8')
                    logger.debug(f"Found README: {readme_file}")
                    # 限制长度，避免太长
                    if len(content) > 10000:
                        content = content[:10000] + "\n... (truncated)"
                    return content
                except Exception as e:
                    logger.warning(f"Failed to read README: {e}")
        
        return ""
    
    def _analyze_structure(self, repo_path: str) -> Dict[str, Any]:
        """分析代码结构"""
        structure = {
            'languages': {},
            'directories': [],
            'total_files': 0
        }
        
        repo_path = Path(repo_path)
        
        # 统计文件类型
        for file_path in repo_path.rglob('*'):
            if file_path.is_file():
                # 跳过隐藏文件和常见非代码目录
                if any(part.startswith('.') for part in file_path.parts):
                    continue
                if any(part in ['node_modules', '__pycache__', 'venv', '.git'] for part in file_path.parts):
                    continue
                
                structure['total_files'] += 1
                ext = file_path.suffix.lower()
                if ext:
                    structure['languages'][ext] = structure['languages'].get(ext, 0) + 1
        
        # 找出主要目录
        for item in repo_path.iterdir():
            if item.is_dir() and not item.name.startswith('.') and item.name not in ['node_modules', '__pycache__']:
                structure['directories'].append(item.name)
        
        return structure
    
    def _find_main_files(self, repo_path: str) -> List[str]:
        """找出主要代码文件"""
        main_files = []
        repo_path = Path(repo_path)
        
        # 优先查找的文件名模式
        priority_patterns = [
            'main.py', 'main.js', 'main.cpp', 'main.c',
            'index.py', 'index.js', 'app.py', 'app.js',
            '__init__.py', 'setup.py', 'Cargo.toml', 'package.json'
        ]
        
        # 根目录优先
        for pattern in priority_patterns:
            for file_path in repo_path.glob(pattern):
                if file_path.is_file():
                    main_files.append(str(file_path.relative_to(repo_path)))
        
        # 再找 src 目录下的主要文件
        src_dirs = ['src', 'lib', 'source']
        for src_dir in src_dirs:
            src_path = repo_path / src_dir
            if src_path.exists():
                for file_path in src_path.iterdir():
                    if file_path.is_file() and file_path.suffix in ['.py', '.js', '.cpp', '.c', '.h', '.hpp', '.java']:
                        main_files.append(str(file_path.relative_to(repo_path)))
                break  # 只取第一个存在的 src 目录
        
        return main_files[:10]  # 限制数量
    
    def _extract_key_functions(self, repo_path: str) -> List[str]:
        """提取关键函数/类定义"""
        functions = []
        repo_path = Path(repo_path)
        
        # 简单正则提取 Python/JavaScript/C++ 函数定义
        patterns = [
            (r'^def\s+(\w+)\s*\(', 'function'),      # Python
            (r'^class\s+(\w+)', 'class'),           # Python/JS/C++
            (r'^function\s+(\w+)', 'function'),     # JavaScript
            (r'^\w+\s+\w+::\w+\s*\(', 'method'),   # C++
        ]
        
        # 只扫描主要文件
        main_files = self._find_main_files(repo_path)
        
        for file_rel in main_files[:5]:  # 限制文件数量
            file_path = repo_path / file_rel
            if not file_path.exists():
                continue
            
            try:
                content = file_path.read_text(encoding='utf-8', errors='ignore')
                lines = content.split('\n')[:100]  # 只读前100行
                
                for line in lines:
                    for pattern, ftype in patterns:
                        match = re.search(pattern, line.strip())
                        if match:
                            name = match.group(1)
                            if not name.startswith('_'):  # 跳过私有函数
                                functions.append(f"{ftype}: {name}")
                                if len(functions) >= 20:  # 限制数量
                                    return functions
            except Exception as e:
                logger.debug(f"Failed to parse {file_path}: {e}")
        
        return functions
    
    def _find_examples(self, repo_path: str) -> List[str]:
        """查找示例代码"""
        examples = []
        repo_path = Path(repo_path)
        
        # 查找 examples 目录
        example_dirs = ['examples', 'example', 'demo', 'demos', 'samples']
        for ex_dir in example_dirs:
            ex_path = repo_path / ex_dir
            if ex_path.exists():
                for file_path in ex_path.iterdir():
                    if file_path.is_file() and file_path.suffix in ['.py', '.js', '.cpp', '.c', '.md']:
                        examples.append(str(file_path.relative_to(repo_path)))
                        if len(examples) >= 5:
                            return examples
        
        return examples
    
    def _cleanup(self, repo_path: str):
        """清理临时文件"""
        try:
            import shutil
            shutil.rmtree(repo_path)
            logger.debug(f"Cleaned up {repo_path}")
        except Exception as e:
            logger.warning(f"Failed to cleanup {repo_path}: {e}")
    
    def format_for_prompt(self, analysis: RepoAnalysis) -> str:
        """将分析结果格式化为 LLM 提示词"""
        sections = []
        
        # 1. README 摘要
        if analysis.readme_content:
            sections.append("=== 项目 README ===")
            # 提取 README 的前几段（通常是项目描述）
            paragraphs = analysis.readme_content.split('\n\n')[:3]
            sections.append('\n\n'.join(paragraphs))
        
        # 2. 代码结构
        if analysis.code_structure:
            sections.append("\n=== 代码结构 ===")
            if analysis.code_structure.get('languages'):
                sections.append(f"主要语言: {', '.join(analysis.code_structure['languages'].keys())[:5]}")
            if analysis.code_structure.get('directories'):
                sections.append(f"主要目录: {', '.join(analysis.code_structure['directories'][:5])}")
        
        # 3. 关键功能
        if analysis.key_functions:
            sections.append("\n=== 主要功能/类 ===")
            sections.append('\n'.join(analysis.key_functions[:10]))
        
        # 4. 示例文件
        if analysis.examples:
            sections.append("\n=== 示例文件 ===")
            sections.append('\n'.join(analysis.examples[:5]))
        
        return '\n'.join(sections)


# 全局分析器实例
_repo_analyzer = None

def get_repo_analyzer() -> RepoAnalyzer:
    """获取 RepoAnalyzer 实例"""
    global _repo_analyzer
    if _repo_analyzer is None:
        _repo_analyzer = RepoAnalyzer()
    return _repo_analyzer
