#!/usr/bin/env python3
"""
代码执行器主类

整合所有代码执行组件，提供统一的执行接口：
- CodeGenerator: 代码生成
- SafeCodeModifier: 安全修改
- RepositoryManager: 仓库管理
- ChangeValidator: 变更验证
"""

from core.logging import get_logger
from typing import Dict, List, Optional, Any
from pathlib import Path

from .code_generator import CodeGenerator
from .safe_modifier import SafeCodeModifier
from .repo_manager import RepositoryManager
from .change_validator import ChangeValidator
from .code_analyzer import CodeAnalyzer
from knowledge_base.success_case_store import SuccessCaseStore, create_case_store
from knowledge_base.knowledge_sync import KnowledgeSyncManager, create_sync_manager

logger = get_logger(__name__)


class CodeExecutor:
    """
    代码执行器
    
    整合代码生成、修改、版本控制的完整工作流：
    1. 分析需求
    2. 获取仓库上下文
    3. 生成代码修改
    4. 安全应用修改
    5. 验证变更
    6. 创建 PR
    """
    
    def __init__(
        self,
        code_generator: CodeGenerator,
        repo_manager: RepositoryManager,
        safe_modifier: SafeCodeModifier,
        validator: ChangeValidator,
        code_analyzer: CodeAnalyzer = None,
        case_store: SuccessCaseStore = None,
        sync_manager: KnowledgeSyncManager = None
    ):
        """
        初始化代码执行器
        
        Args:
            code_generator: 代码生成器
            repo_manager: 仓库管理器
            safe_modifier: 安全修改器
            validator: 变更验证器
            code_analyzer: 代码分析器（可选，默认创建新实例）
            case_store: 案例存储器（可选，用于保存成功案例）
            sync_manager: 知识库同步管理器（可选，用于推送到资料仓库）
        """
        self.code_gen = code_generator
        self.repo_mgr = repo_manager
        self.modifier = safe_modifier
        self.validator = validator
        self.code_analyzer = code_analyzer or CodeAnalyzer()
        self.case_store = case_store or create_case_store()
        
        # 创建同步管理器（可能返回 None 如果未配置）
        if sync_manager is None:
            try:
                self.sync_manager = create_sync_manager()
            except Exception as e:
                logger.debug(f"[CodeExecutor] 同步管理器初始化失败: {e}")
                self.sync_manager = None
        else:
            self.sync_manager = sync_manager
        
        # 存储执行过程中的原始内容，用于创建案例
        self._execution_context = {}
        
        # 初始化日志改为 debug 级别，避免启动时输出过多信息
        logger.debug("[CodeExecutor] 代码执行器初始化完成")
        logger.debug(f"[CodeExecutor]   案例存储: {'已启用' if self.case_store else '未启用'}")
        logger.debug(f"[CodeExecutor]   知识同步: {'已启用' if self.sync_manager else '未启用'}")
        
        if self.sync_manager:
            logger.debug(f"[CodeExecutor]   知识库仓库: {self.sync_manager.knowledge_repo_url}")
    
    def execute_task(
        self,
        task_type: str,
        instruction: str,
        context: str,
        repo_full_name: str,
        issue_number: int,
        github_token: str = None,
        files_to_modify: List[str] = None
    ) -> Dict[str, Any]:
        """
        执行代码任务
        
        Args:
            task_type: 任务类型 (fix_issue, implement_feature, etc.)
            instruction: 用户指令
            context: 完整上下文（Issue 信息 + 知识库参考）
            repo_full_name: 仓库全名 (owner/repo)
            issue_number: Issue 编号
            github_token: GitHub 安装令牌
            files_to_modify: 指定要修改的文件列表
            
        Returns:
            执行结果，包含状态、PR 信息、错误等
        """
        logger.info(f"[CodeExecutor] ========================================")
        logger.info(f"[CodeExecutor] 开始执行任务: {task_type}")
        logger.info(f"[CodeExecutor] 仓库: {repo_full_name}#{issue_number}")
        logger.info(f"[CodeExecutor] 指令长度: {len(instruction)} 字符")
        logger.info(f"[CodeExecutor] 上下文长度: {len(context)} 字符")
        logger.info(f"[CodeExecutor] 指定修改文件: {files_to_modify or '未指定（自动分析）'}")
        logger.info(f"[CodeExecutor] ========================================")
        
        # 解析仓库信息
        owner, repo = repo_full_name.split('/')
        
        # 构造分支名
        branch_name = f"agent-fix-{issue_number}"
        
        # 构造认证克隆 URL
        clone_url = None
        if github_token:
            clone_url = f"https://x-access-token:{github_token}@github.com/{repo_full_name}.git"
            logger.debug(f"[CodeExecutor] 使用 GitHub Token 认证")
        else:
            logger.warning(f"[CodeExecutor] 未提供 GitHub Token，将使用匿名访问")
        
        try:
            # 初始化执行上下文（用于后续创建案例）
            self._execution_context = {
                'repo': repo_full_name,
                'issue_number': issue_number,
                'instruction': instruction,
                'original_contents': {},
                'modified_contents': {},
                'files_modified': [],
                'success': False
            }
            
            # Step 1: 克隆/更新仓库
            logger.info(f"[CodeExecutor] Step 1: 准备仓库 {repo_full_name}...")
            repo_path = self.repo_mgr.clone_or_update(clone_url, owner, repo)
            logger.info(f"[CodeExecutor]   仓库路径: {repo_path}")
            
            # Step 2: 创建分支
            logger.info(f"[CodeExecutor] Step 2: 创建分支 {branch_name}...")
            self.repo_mgr.create_branch(repo_path, branch_name)
            logger.info(f"[CodeExecutor]   分支创建成功")
            
            # Step 3: 分析需求并生成修改
            logger.info(f"[CodeExecutor] Step 3: 分析并生成修改...")
            files_modified = []
            
            if files_to_modify:
                # 修改指定文件
                for file_path in files_to_modify:
                    success = self._modify_file(
                        repo_path, file_path, instruction, context
                    )
                    if success:
                        files_modified.append(file_path)
            else:
                # AI 分析并选择文件
                files_to_edit = self._analyze_files_to_edit(
                    repo_path, instruction, context
                )
                for file_path in files_to_edit:
                    success = self._modify_file(
                        repo_path, file_path, instruction, context
                    )
                    if success:
                        files_modified.append(file_path)
            
            if not files_modified:
                return {
                    "status": "failed",
                    "error": "没有成功修改任何文件"
                }
            
            # Step 4: 提交并推送
            commit_message = f"fix: {instruction[:50]}... (fixes #{issue_number})"
            has_changes = self.repo_mgr.commit_and_push(
                repo_path, commit_message, branch_name, clone_url
            )
            
            if not has_changes:
                return {
                    "status": "failed",
                    "error": "没有可提交的变更"
                }
            
            # Step 5: 创建 PR
            if github_token:
                logger.info(f"Creating PR with token (length: {len(github_token)})")
                try:
                    from github_api.github_client import GitHubClient
                    # Create client with token directly (for code executor)
                    github = GitHubClient(token=github_token)
                    
                    pr_title = f"[Agent] {instruction[:80]}"
                    
                    # 构建 PR body，包含代码分析信息
                    pr_body_parts = [
                        "🤖 此 PR 由 GitHub Agent 自动创建",
                        "",
                        "## 修改说明",
                        "",
                        instruction,
                        "",
                        "## 代码分析",
                        ""
                    ]
                    
                    # 添加分析推理（如果有）
                    if hasattr(self, '_last_analysis_reasoning') and self._last_analysis_reasoning:
                        pr_body_parts.append(self._last_analysis_reasoning)
                        pr_body_parts.append("")
                    
                    pr_body_parts.extend([
                        "## 修改的文件",
                        "",
                        chr(10).join([f'- `{f}`' for f in files_modified]),
                        "",
                        "---",
                        f"fixes #{issue_number}"
                    ])
                    
                    pr_body = "\n".join(pr_body_parts)
                    logger.info(f"Creating PR: {pr_title}")
                    logger.info(f"  Owner: {owner}, Repo: {repo}")
                    logger.info(f"  Head: {branch_name}, Base: main")
                    
                    pr = github.create_pull_request(
                        owner, repo,
                        title=pr_title,
                        head=branch_name,
                        base="main",
                        body=pr_body
                    )
                    
                    if pr:
                        logger.info(f"✅ PR created successfully: #{pr['number']} - {pr['html_url']}")
                        
                        # 记录执行成功并保存案例
                        self._execution_context['success'] = True
                        self._execution_context['pr_number'] = pr['number']
                        self._save_success_case()
                        
                        return {
                            "status": "completed",
                            "pr_number": pr["number"],
                            "pr_url": pr["html_url"],
                            "files_modified": files_modified,
                            "branch": branch_name
                        }
                    else:
                        logger.error("❌ PR creation returned None")
                except Exception as e:
                    logger.exception(f"❌ Failed to create PR: {e}")
            else:
                logger.warning("⚠️  No GitHub token provided, cannot create PR")
            
            # 没有 GitHub token 或 PR 创建失败，只能返回分支信息
            return {
                "status": "completed",
                "branch": branch_name,
                "files_modified": files_modified,
                "message": "分支已推送，但 PR 创建失败，请手动创建 PR"
            }
        
        except Exception as e:
            logger.exception("代码执行失败")
            return {
                "status": "failed",
                "error": str(e)
            }
    
    def _analyze_files_to_edit(
        self,
        repo_path: Path,
        instruction: str,
        context: str
    ) -> List[str]:
        """
        分析需要修改的文件
        
        使用 CodeAnalyzer 进行智能分析，理解代码结构和依赖关系
        
        Args:
            repo_path: 仓库本地路径
            instruction: 用户指令
            context: 完整上下文
            
        Returns:
            需要修改的文件列表
        """
        logger.info("使用 CodeAnalyzer 分析需要修改的文件...")
        
        try:
            # 使用代码分析器进行深度分析
            files_to_modify, dependency_graph, reasoning = self.code_analyzer.analyze_for_issue(
                repo_path=repo_path,
                issue_title=instruction[:100],  # 前100字符作为标题
                issue_body=instruction,
                files_to_analyze=None  # 自动发现所有代码文件
            )
            
            logger.info(f"CodeAnalyzer 建议修改文件: {files_to_modify}")
            logger.debug(f"分析推理:\n{reasoning}")
            
            # 存储依赖图供后续使用（可以通过扩展属性存储）
            self._last_dependency_graph = dependency_graph
            self._last_analysis_reasoning = reasoning
            
            return files_to_modify
            
        except Exception as e:
            logger.warning(f"CodeAnalyzer 分析失败，回退到简单分析: {e}")
            return self._fallback_file_analysis(repo_path, instruction, context)
    
    def _fallback_file_analysis(
        self,
        repo_path: Path,
        instruction: str,
        context: str
    ) -> List[str]:
        """
        回退方案：使用简单的文件名匹配
        
        当 CodeAnalyzer 失败时使用
        """
        logger.info("使用回退方案分析文件...")
        
        # 获取仓库文件列表（Python 和 Arduino C++）
        all_files = []
        for pattern in ["*.py", "*.cpp", "*.c", "*.h", "*.hpp", "*.ino"]:
            files = self.repo_mgr.list_files(repo_path, pattern)
            all_files.extend(files[:20])
        
        # 构建分析提示
        prompt = f"""分析以下 Issue 指令，判断需要修改哪些文件。

## 指令

{instruction}

## 上下文

{context[:500]}

## 仓库文件列表

{chr(10).join(all_files[:30])}

## 输出格式

只返回 JSON 数组：
```json
["src/main.py", "src/utils.py"]
```

最多选择 3 个最相关的文件。如果没有合适的文件，返回空数组 []。"""
        
        response = self.code_gen._generate(prompt, temperature=0.1)
        
        try:
            import json
            import re
            
            # 提取 JSON
            json_match = re.search(r'\[.*?\]', response, re.DOTALL)
            if json_match:
                files = json.loads(json_match.group())
                logger.info(f"AI 选择修改文件: {files}")
                return files
        except Exception as e:
            logger.warning(f"解析文件列表失败: {e}")
        
        # 失败时返回空列表
        return []
    
    def _modify_file(
        self,
        repo_path: Path,
        file_path: str,
        instruction: str,
        context: str
    ) -> bool:
        """
        修改单个文件
        
        Args:
            repo_path: 仓库本地路径
            file_path: 文件相对路径
            instruction: 修改指令
            context: 完整上下文
            
        Returns:
            是否成功
        """
        logger.info(f"[CodeExecutor] 修改文件: {file_path}")
        logger.debug(f"[CodeExecutor]   指令: {instruction[:100]}...")
        
        # 获取当前内容
        logger.debug(f"[CodeExecutor]   读取原始内容...")
        original_content = self.repo_mgr.get_file_content(repo_path, file_path)
        
        if original_content is None:
            logger.debug(f"[CodeExecutor]   文件不存在，检查是否应该创建...")
            # 文件不存在，可能是创建新文件
            if self._should_create_new_file(file_path, instruction):
                logger.info(f"[CodeExecutor]   创建新文件: {file_path}")
                new_content = self.modifier.create_new_file(
                    file_path, instruction, context
                )
                logger.debug(f"[CodeExecutor]   新文件内容 ({len(new_content)} 字符)")
                
                self.repo_mgr.write_file(repo_path, file_path, new_content)
                logger.debug(f"[CodeExecutor]   文件写入完成")
                
                # 验证新文件
                logger.debug(f"[CodeExecutor]   验证新文件...")
                val_result = self.validator.validate_file(file_path, new_content)
                if not val_result.is_valid:
                    logger.error(f"[CodeExecutor] ❌ 新文件验证失败: {val_result.message}")
                    return False
                
                logger.info(f"[CodeExecutor] ✅ 新文件创建成功: {file_path}")
                
                # 输出警告（如果有）
                if val_result.warnings:
                    logger.warning(f"[CodeExecutor] ⚠️  新文件警告: {val_result.warnings}")
                
                return True
            else:
                logger.warning(f"[CodeExecutor] ⚠️  文件不存在且不应创建: {file_path}")
                return False
        
        # 修改现有文件
        logger.debug(f"[CodeExecutor]   原始内容: {len(original_content)} 字符, {original_content.count(chr(10))+1} 行")
        
        try:
            logger.debug(f"[CodeExecutor]   调用 AI 修改器...")
            new_content = self.modifier.modify_file(
                file_path, original_content, instruction
            )
            logger.debug(f"[CodeExecutor]   修改器返回: {len(new_content)} 字符")
            
            # 检查是否真的修改了
            if new_content == original_content:
                logger.warning(f"[CodeExecutor] ⚠️  文件内容未变化: {file_path}")
                logger.warning(f"[CodeExecutor]    AI 修改器没有产生实际变更")
                return False
            
            content_diff = len(new_content) - len(original_content)
            logger.debug(f"[CodeExecutor]   内容变化: {content_diff:+,} 字符")
            
            # 验证修改（使用增强的修改验证）
            logger.debug(f"[CodeExecutor]   验证修改...")
            val_result = self.validator.validate_modification(
                file_path, original_content, new_content, instruction
            )
            if not val_result.is_valid:
                logger.error(f"[CodeExecutor] ❌ 修改验证失败: {val_result.message}")
                logger.error(f"[CodeExecutor]    错误详情: {val_result.errors}")
                return False
            
            logger.debug(f"[CodeExecutor]   验证通过")
            
            # 输出警告（如果有）
            if val_result.warnings:
                logger.warning(f"[CodeExecutor] ⚠️  修改警告: {val_result.warnings}")
            
            # 写入修改
            logger.debug(f"[CodeExecutor]   写入文件...")
            self.repo_mgr.write_file(repo_path, file_path, new_content)
            
            # 验证写入成功
            logger.debug(f"[CodeExecutor]   验证写入...")
            saved_content = self.repo_mgr.get_file_content(repo_path, file_path)
            if saved_content != new_content:
                logger.error(f"[CodeExecutor] ❌ 文件写入验证失败: {file_path}")
                logger.error(f"[CodeExecutor]    期望: {len(new_content)} 字符")
                logger.error(f"[CodeExecutor]    实际: {len(saved_content)} 字符")
                return False
            
            logger.info(f"[CodeExecutor] ✅ 文件修改成功: {file_path} ({len(original_content)} → {len(new_content)} 字符, {content_diff:+,})")
            
            # 保存到执行上下文（用于创建案例）
            self._execution_context['original_contents'][file_path] = original_content
            self._execution_context['modified_contents'][file_path] = new_content
            self._execution_context['files_modified'].append(file_path)
            
            return True
        
        except Exception as e:
            logger.error(f"修改文件失败 {file_path}: {e}")
            return False
    
    def _should_create_new_file(self, file_path: str, instruction: str) -> bool:
        """
        判断是否应该创建新文件
        
        根据指令内容判断用户的意图
        
        Args:
            file_path: 文件路径
            instruction: 指令
            
        Returns:
            是否应该创建
        """
        # 简单的启发式判断
        create_keywords = [
            "创建", "新建", "添加", "create", "new", "add",
            "增加", "implement", "添加文件", "create file"
        ]
        
        instruction_lower = instruction.lower()
        for keyword in create_keywords:
            if keyword.lower() in instruction_lower:
                return True
        
        # 检查是否提到特定的新文件
        if file_path.split('/')[-1].lower() in instruction_lower:
            return True
        
        return False
    
    def _save_success_case(self):
        """保存成功案例到知识库"""
        if not self.case_store:
            logger.debug("[CodeExecutor] 案例存储未启用，跳过保存")
            return
        
        ctx = self._execution_context
        
        if not ctx.get('success') or not ctx.get('files_modified'):
            logger.debug("[CodeExecutor] 执行未成功或无修改，跳过保存案例")
            return
        
        case_id = None
        try:
            logger.info("[CodeExecutor] 保存成功案例到知识库...")
            
            # 创建案例
            case = self.case_store.create_case_from_execution(
                repo=ctx['repo'],
                issue_number=ctx['issue_number'],
                issue_title=ctx['instruction'][:100],  # 前100字符作为标题
                issue_body=ctx['instruction'],
                files_modified=ctx['files_modified'],
                original_contents=ctx['original_contents'],
                modified_contents=ctx['modified_contents'],
                success=True
            )
            
            # 更新 PR 信息
            if ctx.get('pr_number'):
                case.outcome.pr_number = ctx['pr_number']
            
            # 保存到本地
            case_id = self.case_store.save_case(case)
            
            logger.info(f"[CodeExecutor] ✅ 案例保存成功: {case_id}")
            
            # 触发同步到资料仓库（如果配置了）
            if self.sync_manager and case_id:
                logger.info("[CodeExecutor] 触发知识库同步...")
                try:
                    # 异步同步（不阻塞主流程）
                    import threading
                    sync_thread = threading.Thread(
                        target=self._sync_case_async,
                        args=(case_id,),
                        daemon=True
                    )
                    sync_thread.start()
                    logger.info("[CodeExecutor]   同步任务已启动（后台执行）")
                except Exception as e:
                    logger.warning(f"[CodeExecutor]   同步任务启动失败: {e}")
            
        except Exception as e:
            # 案例保存失败不应影响主流程
            logger.error(f"[CodeExecutor] ⚠️ 案例保存失败: {e}")
            logger.debug(f"[CodeExecutor]   错误详情: {e}", exc_info=True)
    
    def _sync_case_async(self, case_id: str):
        """异步同步案例"""
        try:
            if self.sync_manager:
                success = self.sync_manager.sync_case(case_id)
                if success:
                    logger.info(f"[CodeExecutor] ✅ 案例同步到资料仓库成功: {case_id}")
                else:
                    logger.warning(f"[CodeExecutor] ⚠️ 案例同步失败，已加入重试队列: {case_id}")
        except Exception as e:
            logger.error(f"[CodeExecutor] ❌ 案例同步异常: {e}")
