#!/usr/bin/env python3
"""
安全代码修改器
使用 SEARCH/REPLACE 格式精确修改代码，避免误删

增强功能：
- 模糊匹配：支持一定程度的空白字符差异
- 相似度匹配：使用 difflib 找到最佳匹配
- 多重回退策略：精确 → 规范化 → 相似度 → 失败
"""

import re
from core.logging import get_logger
import difflib
from typing import Optional, Tuple

logger = get_logger(__name__)


class SafeCodeModifier:
    """
    安全代码修改器
    
    使用 diff 风格的 SEARCH/REPLACE 格式：
    - 精确匹配原始代码
    - 只替换匹配的部分
    - 不匹配时拒绝修改（安全回退）
    """
    
    def __init__(self, code_generator=None):
        """
        初始化安全修改器
        
        Args:
            code_generator: 可选的代码生成器，用于 AI 辅助修改
        """
        self.code_generator = code_generator
    
    def modify_file(
        self,
        file_path: str,
        file_content: str,
        instruction: str
    ) -> str:
        """
        安全地修改文件
        
        Args:
            file_path: 文件路径（用于日志）
            file_content: 当前文件内容
            instruction: 修改指令
            
        Returns:
            修改后的文件内容
            
        Raises:
            ValueError: 如果无法安全修改
        """
        # 如果文件不大（<=100行），使用精确替换
        lines = file_content.split('\n')
        if len(lines) <= 100:
            return self._precise_replace(file_path, file_content, instruction)
        
        # 大文件：分段处理
        return self._chunked_modify(file_path, file_content, instruction)
    
    def _precise_replace(
        self,
        file_path: str,
        file_content: str,
        instruction: str
    ) -> str:
        """
        精确替换 - 适用于小文件
        
        让 AI 生成 SEARCH/REPLACE 块，然后精确替换
        """
        # 如果有代码生成器，使用 AI 辅助
        if self.code_generator:
            return self._ai_assisted_replace(file_path, file_content, instruction)
        
        # 否则返回原始内容（需要外部处理）
        logger.warning(f"没有代码生成器，无法修改: {file_path}")
        return file_content
    
    def _fuzzy_search_replace(
        self,
        file_content: str,
        search_text: str,
        replace_text: str,
        threshold: float = 0.85
    ) -> Tuple[str, str]:
        """
        模糊搜索替换
        
        策略（按优先级）：
        1. 精确匹配
        2. 规范化匹配（忽略行尾空白和换行符差异）
        3. 相似度匹配（使用 difflib.SequenceMatcher）
        
        Args:
            file_content: 原始文件内容
            search_text: AI 生成的 SEARCH 文本
            replace_text: AI 生成的 REPLACE 文本
            threshold: 相似度阈值（0-1）
            
        Returns:
            (new_content, match_method)
            - new_content: 替换后的内容
            - match_method: 使用的匹配方法（"exact", "normalized", "fuzzy"）
            
        Raises:
            ValueError: 所有匹配方法都失败
        """
        logger.debug(f"[SafeModifier] 开始模糊匹配")
        logger.debug(f"[SafeModifier] SEARCH 文本 ({len(search_text)} 字符, {search_text.count(chr(10))+1} 行):")
        logger.debug(f"[SafeModifier]   {search_text[:200]}{'...' if len(search_text) > 200 else ''}")
        logger.debug(f"[SafeModifier] REPLACE 文本 ({len(replace_text)} 字符, {replace_text.count(chr(10))+1} 行):")
        logger.debug(f"[SafeModifier]   {replace_text[:200]}{'...' if len(replace_text) > 200 else ''}")
        logger.debug(f"[SafeModifier] 文件内容 ({len(file_content)} 字符)")
        
        # 1. 精确匹配
        logger.debug(f"[SafeModifier] 尝试精确匹配...")
        if search_text in file_content:
            new_content = file_content.replace(search_text, replace_text, 1)
            logger.debug(f"[SafeModifier] ✅ 精确匹配成功")
            return new_content, "exact"
        
        logger.debug(f"[SafeModifier] 精确匹配失败，尝试规范化匹配...")
        logger.debug(f"[SafeModifier]   SEARCH MD5: {hash(search_text) % 10000}")
        logger.debug(f"[SafeModifier]   内容 MD5: {hash(file_content[:len(search_text)]) % 10000}")
        
        # 2. 规范化匹配（忽略行尾空白）
        def normalize(text):
            lines = text.split('\n')
            lines = [rstrip(line) for line in lines]
            return '\n'.join(lines)
        
        def rstrip(line):
            # 安全地移除行尾空白
            return line.rstrip()
        
        normalized_search = normalize(search_text)
        normalized_content = normalize(file_content)
        
        if normalized_search in normalized_content:
            # 找到在规范化内容中的位置
            idx = normalized_content.find(normalized_search)
            # 映射回原始内容
            # 简单方法：在原始内容中找相似区域
            new_content = self._apply_normalized_replace(
                file_content, search_text, replace_text
            )
            if new_content != file_content:
                return new_content, "normalized"
        
        logger.debug(f"[SafeModifier] 规范化匹配失败，尝试相似度匹配...")
        logger.debug(f"[SafeModifier] 相似度阈值: {threshold}")
        
        # 3. 相似度匹配（基于行）
        best_match = self._find_best_line_match(
            file_content, search_text, threshold
        )
        
        if best_match:
            actual_text, confidence = best_match
            logger.info(f"[SafeModifier] 找到模糊匹配 (置信度: {confidence:.2f})")
            logger.debug(f"[SafeModifier]   期望 ({len(search_text)} 字符):")
            for i, line in enumerate(search_text.split('\n')[:5], 1):
                logger.debug(f"[SafeModifier]     {i}: {line[:80]}")
            logger.debug(f"[SafeModifier]   实际 ({len(actual_text)} 字符):")
            for i, line in enumerate(actual_text.split('\n')[:5], 1):
                logger.debug(f"[SafeModifier]     {i}: {line[:80]}")
            
            new_content = file_content.replace(actual_text, replace_text, 1)
            return new_content, f"fuzzy({confidence:.2f})"
        
        # 所有方法都失败
        logger.error(f"[SafeModifier] ❌ 所有匹配方法都失败")
        logger.error(f"[SafeModifier]   SEARCH ({len(search_text)} 字符):")
        logger.error(f"     {search_text[:300]}{'...' if len(search_text) > 300 else ''}")
        logger.error(f"[SafeModifier]   文件内容前 500 字符:")
        logger.error(f"     {file_content[:500]}{'...' if len(file_content) > 500 else ''}")
        raise ValueError(
            f"无法找到匹配的文本（尝试了精确、规范化、相似度匹配）"
        )
    
    def _apply_normalized_replace(
        self,
        file_content: str,
        search_text: str,
        replace_text: str
    ) -> str:
        """
        应用规范化替换
        
        策略：基于行内容匹配
        """
        file_lines = file_content.split('\n')
        search_lines = search_text.split('\n')
        
        # 移除空行进行比较
        search_lines_stripped = [l.strip() for l in search_lines if l.strip()]
        
        if not search_lines_stripped:
            return file_content
        
        # 查找匹配的起始行
        for i in range(len(file_lines) - len(search_lines) + 1):
            window = file_lines[i:i + len(search_lines)]
            window_stripped = [l.strip() for l in window if l.strip()]
            
            if len(window_stripped) != len(search_lines_stripped):
                continue
            
            # 比较非空行
            match = all(
                w == s for w, s in zip(window_stripped, search_lines_stripped)
            )
            
            if match:
                # 替换这一区域
                original_block = '\n'.join(file_lines[i:i + len(search_lines)])
                new_content = file_content.replace(original_block, replace_text, 1)
                return new_content
        
        return file_content
    
    def _find_best_line_match(
        self,
        file_content: str,
        search_text: str,
        threshold: float
    ) -> Optional[Tuple[str, float]]:
        """
        使用 difflib 找到最佳匹配
        
        基于行的相似度比较
        """
        search_lines = search_text.split('\n')
        num_search_lines = len(search_lines)
        
        if num_search_lines == 0:
            return None
        
        file_lines = file_content.split('\n')
        best_match = None
        best_ratio = 0.0
        
        # 滑动窗口查找最佳匹配
        for i in range(len(file_lines) - num_search_lines + 1):
            window = file_lines[i:i + num_search_lines]
            window_text = '\n'.join(window)
            
            # 计算相似度
            ratio = difflib.SequenceMatcher(
                None, search_text, window_text
            ).ratio()
            
            if ratio > best_ratio:
                best_ratio = ratio
                best_match = window_text
        
        if best_match and best_ratio >= threshold:
            return (best_match, best_ratio)
        
        return None
    
    def _ai_assisted_replace(
        self,
        file_path: str,
        file_content: str,
        instruction: str
    ) -> str:
        """
        AI 辅助的精确替换（增强版，支持模糊匹配）
        
        让 AI 生成 SEARCH/REPLACE 格式，然后执行替换
        """
        # 构建提示词
        prompt = f"""提供代码修改的 SEARCH/REPLACE 格式。

## 文件

{file_path}

## 当前内容

```
{file_content}
```

## 修改指令

{instruction}

## 输出格式

必须严格使用以下格式：

SEARCH:
```
要查找的精确代码（包含足够的上下文，3-5行）
```
REPLACE:
```
替换后的新代码
```

⚠️ **重要要求**：
1. **必须产生实际修改** - SEARCH 和 REPLACE 必须不同
2. **明确修改内容** - 在 REPLACE 中添加注释说明修改了什么
3. **SEARCH 块必须能在原代码中精确匹配**
4. **包含足够的上下文** 确保匹配唯一性（3-5行）
5. **只修改需要修改的地方**

示例：
SEARCH:
```
  writeReg(0x01, 0xEF);  // User's temp fix
```
REPLACE:
```
  writeReg(0x01, 0x21);  // Fixed: correct value for 1Hz output
```"""
        
        # 调用 AI 生成 SEARCH/REPLACE
        logger.info(f"请求 AI 生成精确替换: {file_path}")
        response = self.code_generator._generate(prompt, temperature=0.1)
        
        # 解析 SEARCH/REPLACE
        search_match = re.search(r'SEARCH:\s*```\s*\n?(.*?)\n?```', response, re.DOTALL)
        replace_match = re.search(r'REPLACE:\s*```\s*\n?(.*?)\n?```', response, re.DOTALL)
        
        if not search_match or not replace_match:
            logger.error("AI 没有提供有效的 SEARCH/REPLACE 格式")
            raise ValueError("AI 没有提供有效的 SEARCH/REPLACE 格式")
        
        search_text = search_match.group(1).rstrip('\n')
        replace_text = replace_match.group(1).rstrip('\n')
        
        # 使用模糊匹配执行替换
        try:
            new_content, match_method = self._fuzzy_search_replace(
                file_content, search_text, replace_text
            )
            
            # 验证是否真的修改了
            if new_content == file_content:
                logger.warning(f"⚠️  替换后内容未变化，SEARCH 和 REPLACE 可能相同: {file_path}")
                raise ValueError("SEARCH 和 REPLACE 内容相同，没有实际修改")
            
            logger.info(f"✅ 替换成功 [{match_method}]: {file_path} ({len(search_text)} → {len(replace_text)} 字符)")
            return new_content
            
        except ValueError as e:
            logger.error(f"❌ 替换失败: {file_path} - {e}")
            logger.debug(f"SEARCH 文本 ({len(search_text)} 字符):")
            logger.debug(search_text[:200])
            logger.debug(f"文件内容前200字符:")
            logger.debug(file_content[:200])
            raise
    
    def _chunked_modify(
        self,
        file_path: str,
        file_content: str,
        instruction: str
    ) -> str:
        """
        分段修改 - 适用于大文件
        
        1. 让 AI 找出需要修改的行号范围
        2. 提取相关代码段
        3. 对代码段使用精确替换
        4. 合并回原始文件
        """
        lines = file_content.split('\n')
        total_lines = len(lines)
        
        logger.info(f"大文件 ({total_lines} 行)，使用分段处理: {file_path}")
        logger.debug(f"原始内容 MD5: {hash(file_content) % 10000}")  # 简单指纹
        
        # 第一步：让 AI 找出需要修改的行号
        line_prompt = f"""分析大文件，找出需要修改的行号。

文件: {file_path}
总行数: {total_lines}

文件开头（前50行）：
```
{'\n'.join(lines[:50])}
```

修改指令: {instruction}

## 任务

找出需要修改的行号范围。

## 输出格式

返回 JSON：
```json
{{
  "modifications": [
    {{"start_line": 10, "end_line": 20, "description": "修改说明"}}
  ]
}}
```"""
        
        response = self.code_generator._generate(line_prompt, temperature=0.1)
        
        try:
            # 解析 JSON
            import json
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                modifications = data.get("modifications", [])
                
                # 应用修改
                new_content = file_content
                total_changes = 0
                for i, mod in enumerate(modifications):
                    start = mod.get("start_line", 1) - 1
                    end = mod.get("end_line", total_lines)
                    desc = mod.get("description", "")
                    
                    logger.info(f"  修改 {i+1}/{len(modifications)}: 行 {start+1}-{end} - {desc}")
                    
                    # 提取上下文（前后各3行）
                    context_start = max(0, start - 3)
                    context_end = min(total_lines, end + 3)
                    chunk = '\n'.join(lines[context_start:context_end])
                    
                    logger.debug(f"  原始 chunk ({len(chunk)} 字符):")
                    logger.debug(f"  {chunk[:200]}...")
                    
                    # 修改这个 chunk
                    try:
                        modified_chunk = self._ai_assisted_replace(
                            file_path,
                            chunk,
                            f"{instruction}\n具体: {desc}"
                        )
                    except Exception as e:
                        logger.error(f"  chunk 修改失败: {e}")
                        continue
                    
                    logger.debug(f"  修改后 chunk ({len(modified_chunk)} 字符):")
                    logger.debug(f"  {modified_chunk[:200]}...")
                    
                    # 检查是否真的修改了
                    if chunk == modified_chunk:
                        logger.warning(f"  ⚠️  chunk {i+1} 没有变化，AI 可能没有实际修改代码")
                        continue
                    
                    # 替换回原内容
                    new_content = new_content.replace(chunk, modified_chunk, 1)
                    total_changes += 1
                    logger.info(f"  ✅ chunk {i+1} 修改完成")
                
                if total_changes == 0:
                    logger.warning(f"⚠️  所有 chunk 都没有实际修改，返回原始内容")
                else:
                    logger.info(f"✅ 共完成 {total_changes} 处修改")
                
                return new_content
        except Exception as e:
            logger.error(f"分段修改失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
        
        # 失败时返回原始内容（安全回退）
        logger.warning(f"⚠️  分段修改失败，返回原始内容: {file_path}")
        return file_content
    
    def create_new_file(
        self,
        file_path: str,
        instruction: str,
        context: str = None
    ) -> str:
        """
        创建新文件
        
        Args:
            file_path: 新文件路径
            instruction: 创建指令
            context: 可选上下文
            
        Returns:
            新文件内容
        """
        if not self.code_generator:
            raise ValueError("需要代码生成器才能创建文件")
        
        context_str = f"\n\n上下文:\n{context}" if context else ""
        
        prompt = f"""创建新文件。

文件路径: {file_path}
{context_str}

要求:
{instruction}

返回完整的文件内容，不要加 markdown 代码块。"""
        
        logger.info(f"创建新文件: {file_path}")
        content = self.code_generator._generate(prompt, temperature=0.3)
        
        # 清理代码块标记
        return self.code_generator._extract_code(content)
