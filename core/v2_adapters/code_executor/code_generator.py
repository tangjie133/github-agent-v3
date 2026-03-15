#!/usr/bin/env python3
"""
代码生成器
使用本地 Ollama 模型（qwen3-coder）生成代码修改
"""

import os
import json
import re
import requests
from core.logging import get_logger
from typing import List, Dict, Any, Optional

# 设置日志
logger = get_logger(__name__)


class CodeGenerator:
    """
    代码生成器
    
    使用 Ollama 本地模型生成代码：
    - 分析需求并生成代码
    - 支持单文件和多文件修改
    - 自动检测模型参数
    """
    
    def __init__(self, host: str = None, model: str = None):
        """
        初始化代码生成器
        
        Args:
            host: Ollama 服务地址，默认从环境变量读取
            model: 使用的模型名称，默认从环境变量读取
        """
        self.model = model or os.environ.get("OLLAMA_MODEL", "qwen3-coder:30b")
        self.host = host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")
        self.base_url = self.host  # 别名，方便访问
        
        logger.debug(f"代码生成器初始化: 模型={self.model}, 地址={self.host}")
    
    def generate_modification(
        self,
        file_path: str,
        file_content: str,
        instruction: str,
        context: str = None
    ) -> str:
        """
        生成单文件修改
        
        Args:
            file_path: 文件路径
            file_content: 当前文件内容
            instruction: 修改指令
            context: 可选的上下文信息（如知识库查询结果）
            
        Returns:
            修改后的完整文件内容
        """
        # 构建提示词
        prompt = self._build_modification_prompt(
            file_path, file_content, instruction, context
        )
        
        # 调用 Ollama 生成
        logger.info(f"正在生成修改: {file_path}")
        response = self._generate(prompt, temperature=0.3)
        
        # 清理响应，提取代码
        modified_code = self._extract_code(response)
        
        logger.info(f"代码生成完成: {file_path}")
        return modified_code
    
    def generate_multi_file_modification(
        self,
        files: List[Dict[str, str]],
        instruction: str,
        context: str = None
    ) -> List[Dict[str, str]]:
        """
        生成多文件修改
        
        Args:
            files: 文件列表，每项包含 path 和 content
            instruction: 修改指令
            context: 可选的上下文信息
            
        Returns:
            修改后的文件列表
        """
        # 构建提示词
        prompt = self._build_multi_file_prompt(files, instruction, context)
        
        # 调用 Ollama 生成
        logger.info(f"正在生成多文件修改: {len(files)} 个文件")
        response = self._generate(prompt, temperature=0.2)
        
        # 解析 JSON 响应
        try:
            modifications = self._extract_json(response)
            logger.info(f"多文件修改生成完成: {len(modifications)} 个文件")
            return modifications
        except Exception as e:
            logger.error(f"解析多文件修改失败: {e}")
            raise
    
    def analyze_issue_complexity(
        self,
        issue_title: str,
        issue_body: str,
        repo_files: List[str]
    ) -> Dict[str, Any]:
        """
        分析问题复杂度
        
        Args:
            issue_title: Issue 标题
            issue_body: Issue 内容
            repo_files: 仓库文件列表
            
        Returns:
            分析结果，包含复杂度、需要修改的文件等
        """
        # 构建提示词
        files_str = "\n".join(repo_files[:50])  # 限制文件数量
        
        prompt = f"""分析 GitHub Issue 的复杂度。

## Issue 信息

标题: {issue_title}

内容:
```
{issue_body}
```

## 仓库文件

{files_str}

## 分析维度

1. **复杂度评估**：
   - simple: 单文件简单修改
   - medium: 多文件修改，但逻辑清晰
   - complex: 涉及架构变更或需要深入理解

2. **需要修改的文件**：列出具体文件路径

3. **操作类型**：
   - single_file: 单文件修改
   - multi_file_refactor: 多文件重构
   - create_only: 仅创建新文件

## 输出格式

返回 JSON：
```json
{{
  "complexity": "simple|medium|complex",
  "files_to_modify": ["path/to/file1", "path/to/file2"],
  "files_to_create": ["path/to/newfile"],
  "operation": "single_file|multi_file_refactor|create_only",
  "description": "简要描述需要做什么"
}}
```

只返回 JSON，不要有其他内容。"""
        
        # 调用 Ollama
        logger.info(f"正在分析 Issue 复杂度: {issue_title[:50]}")
        response = self._generate(prompt, temperature=0.1)
        
        # 解析结果
        try:
            analysis = self._extract_json(response)
            logger.info(f"复杂度分析完成: {analysis.get('complexity', 'unknown')}")
            return analysis
        except Exception as e:
            logger.error(f"解析复杂度分析失败: {e}")
            # 返回默认结果
            return {
                "complexity": "simple",
                "files_to_modify": [],
                "files_to_create": [],
                "operation": "single_file",
                "description": "自动分析失败，使用默认配置"
            }
    
    def generate_change_description(
        self,
        file_path: str,
        original_content: str,
        modified_content: str,
        instruction: str
    ) -> str:
        """
        生成修改说明
        
        Args:
            file_path: 文件路径
            original_content: 原始内容
            modified_content: 修改后内容
            instruction: 修改指令
            
        Returns:
            修改说明文本
        """
        # 提取部分内容用于对比
        max_preview = 500
        orig_preview = original_content[:max_preview] if len(original_content) > max_preview else original_content
        mod_preview = modified_content[:max_preview] if len(modified_content) > max_preview else modified_content
        
        prompt = f"""描述代码修改的内容。

## 文件

{file_path}

## 原始代码（片段）

```
{orig_preview}
```

## 修改后代码（片段）

```
{mod_preview}
```

## 修改指令

{instruction}

## 任务

请用 3-5 句话描述：
1. 修改了什么
2. 为什么这样修改
3. 解决了什么问题

用中文回答。"""
        
        logger.info(f"正在生成修改说明: {file_path}")
        response = self._generate(prompt, temperature=0.3, num_predict=500)
        
        return response.strip()
    
    def _generate(
        self,
        prompt: str,
        temperature: float = 0.3,
        num_predict: int = None
    ) -> str:
        """
        调用 Ollama 生成文本
        
        Args:
            prompt: 提示词
            temperature: 温度参数（创造性）
            num_predict: 最大生成 token 数
            
        Returns:
            生成的文本
        """
        url = f"{self.host}/api/generate"
        
        # 根据模型设置默认参数
        if "30b" in self.model or "32b" in self.model:
            default_predict = 8000
            num_ctx = 131072  # 128K 上下文
        elif "14b" in self.model:
            default_predict = 6000
            num_ctx = 32768   # 32K 上下文
        else:
            default_predict = 4000
            num_ctx = 16384   # 16K 上下文
        
        num_predict = num_predict or default_predict
        
        data = {
            "model": self.model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": num_predict,
                "num_ctx": num_ctx,
                "top_p": 0.9,
                "top_k": 40
            }
        }
        
        try:
            response = requests.post(url, json=data, timeout=300)
            response.raise_for_status()
            return response.json()["response"]
        except requests.exceptions.ConnectionError:
            raise ConnectionError(f"无法连接到 Ollama: {self.host}")
        except requests.exceptions.Timeout:
            raise TimeoutError("Ollama 请求超时")
    
    def _build_modification_prompt(
        self,
        file_path: str,
        file_content: str,
        instruction: str,
        context: str = None
    ) -> str:
        """构建单文件修改提示词"""
        context_str = f"\n\n## 额外上下文\n\n{context}\n" if context else ""
        
        return f"""修改代码文件。

## 文件信息

路径: {file_path}

当前内容:
```
{file_content}
```
{context_str}
## 修改指令

{instruction}

## 要求

1. 返回完整的修改后文件内容
2. 不要省略任何部分
3. 保持原有代码风格
4. 只修改必要的地方

## 输出

直接返回修改后的完整代码，不要加 markdown 代码块标记。"""
    
    def _build_multi_file_prompt(
        self,
        files: List[Dict[str, str]],
        instruction: str,
        context: str = None
    ) -> str:
        """构建多文件修改提示词"""
        files_str = ""
        for f in files:
            files_str += f"\n### {f['path']}\n```\n{f['content'][:2000]}\n```\n"
        
        context_str = f"\n\n## 额外上下文\n\n{context}\n" if context else ""
        
        return f"""修改多个代码文件。

## 需要修改的文件
{files_str}
{context_str}
## 修改指令

{instruction}

## 输出格式

返回 JSON 数组，每项包含 path 和 content：
```json
[
  {{"path": "file1.cpp", "content": "完整文件内容"}},
  {{"path": "file2.h", "content": "完整文件内容"}}
]
```

只返回 JSON，不要有其他内容。"""
    
    def _extract_code(self, text: str) -> str:
        """从响应中提取代码"""
        # 清理 markdown 代码块
        lines = text.strip().split('\n')
        
        # 移除开头的 ```language
        if lines and lines[0].startswith('```'):
            lines = lines[1:]
        
        # 移除结尾的 ```
        if lines and lines[-1].strip() == '```':
            lines = lines[:-1]
        
        return '\n'.join(lines)
    
    def _extract_json(self, text: str) -> Any:
        """从文本中提取 JSON"""
        import json
        
        # 查找 ```json ... ``` 块
        match = re.search(r'```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```', text, re.DOTALL)
        if match:
            return json.loads(match.group(1))
        
        # 查找单独的 JSON 对象/数组
        match = re.search(r'(\{[\s\S]*\}|\[[\s\S]*\])', text)
        if match:
            return json.loads(match.group(1))
        
        raise ValueError(f"无法从文本中提取 JSON: {text[:200]}")
    
    def check_model(self) -> bool:
        """检查模型是否可用"""
        try:
            url = f"{self.host}/api/tags"
            response = requests.get(url, timeout=5)
            response.raise_for_status()
            
            models = response.json().get("models", [])
            model_names = [m.get("name", "") for m in models]
            
            if self.model in model_names or any(self.model in name for name in model_names):
                return True
            
            logger.warning(f"模型 {self.model} 未找到。可用模型: {model_names}")
            return False
            
        except Exception as e:
            logger.error(f"检查 Ollama 失败: {e}")
            return False
    
    def health_check(self) -> bool:
        """健康检查"""
        try:
            url = f"{self.host}/api/tags"
            response = requests.get(url, timeout=5)
            return response.status_code == 200
        except Exception:
            return False
