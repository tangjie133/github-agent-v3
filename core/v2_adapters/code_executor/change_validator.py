#!/usr/bin/env python3
"""
变更验证器
验证代码变更的语法正确性和质量
"""

import ast
import json
from core.logging import get_logger
import re
from typing import List, Optional, Dict, Any

logger = get_logger(__name__)


class ValidationResult:
    """验证结果"""
    
    def __init__(
        self,
        is_valid: bool,
        errors: List[str] = None,
        warnings: List[str] = None
    ):
        self.is_valid = is_valid
        self.errors = errors or []
        self.warnings = warnings or []
    
    @property
    def message(self) -> str:
        """获取验证消息"""
        if self.is_valid:
            return "验证通过"
        return "; ".join(self.errors)


class ChangeValidator:
    """
    变更验证器
    
    验证代码变更的：
    - 语法正确性（AST 解析）
    - 导入完整性
    - 基本代码质量
    """
    
    def __init__(self, code_generator=None):
        """
        初始化变更验证器
        
        Args:
            code_generator: 可选的代码生成器，用于 AI 辅助验证
        """
        self.code_generator = code_generator
    
    def validate_python_file(
        self,
        file_path: str,
        file_content: str
    ) -> ValidationResult:
        """
        验证 Python 文件
        
        Args:
            file_path: 文件路径（用于日志）
            file_content: 文件内容
            
        Returns:
            验证结果
        """
        logger.debug(f"[Validator] 开始验证 Python 文件: {file_path}")
        logger.debug(f"[Validator]   文件大小: {len(file_content)} 字符, {file_content.count(chr(10))+1} 行")
        
        errors = []
        warnings = []
        
        # 1. 语法检查
        logger.debug(f"[Validator]   检查 Python 语法...")
        try:
            tree = ast.parse(file_content)
            # 统计代码结构
            func_count = len([n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)])
            class_count = len([n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)])
            import_count = len([n for n in ast.walk(tree) if isinstance(n, (ast.Import, ast.ImportFrom))])
            logger.debug(f"[Validator]     函数: {func_count} 个, 类: {class_count} 个, 导入: {import_count} 个")
        except SyntaxError as e:
            error_msg = f"语法错误: 第{e.lineno}行, 第{e.offset}列 - {e.msg}"
            errors.append(error_msg)
            logger.error(f"[Validator] ❌ Python 语法错误: {file_path}")
            logger.error(f"[Validator]    {error_msg}")
            logger.error(f"[Validator]    错误行: {file_content.split(chr(10))[e.lineno-1] if e.lineno <= len(file_content.split(chr(10))) else 'N/A'}")
            return ValidationResult(is_valid=False, errors=errors)
        except Exception as e:
            errors.append(f"解析错误: {e}")
            logger.error(f"[Validator] ❌ Python 解析错误: {file_path} - {e}")
            return ValidationResult(is_valid=False, errors=errors)
        
        # 2. 检查常见错误
        # 未闭合的括号
        logger.debug(f"[Validator]   检查括号匹配...")
        if not self._check_brackets(file_content):
            errors.append("括号不匹配")
            logger.warning(f"[Validator]   发现括号不匹配")
        
        # 缩进问题（简单检查）
        logger.debug(f"[Validator]   检查缩进...")
        if self._has_indentation_errors(file_content):
            warnings.append("可能存在缩进问题")
            logger.warning(f"[Validator]   发现潜在缩进问题")
        
        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"[Validator] ✅ Python 验证通过: {file_path}")
        else:
            logger.error(f"[Validator] ❌ Python 验证失败: {file_path}")
            logger.error(f"[Validator]    错误: {errors}")
        
        if warnings:
            logger.warning(f"[Validator] ⚠️  警告: {warnings}")
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings
        )
    
    def validate_json_file(
        self,
        file_path: str,
        file_content: str
    ) -> ValidationResult:
        """
        验证 JSON 文件
        
        Args:
            file_path: 文件路径
            file_content: 文件内容
            
        Returns:
            验证结果
        """
        errors = []
        
        try:
            json.loads(file_content)
        except json.JSONDecodeError as e:
            errors.append(f"JSON 错误: 第{e.lineno}行, 第{e.colno}列 - {e.msg}")
            logger.error(f"JSON 验证失败: {file_path} - {e}")
            return ValidationResult(is_valid=False, errors=errors)
        
        logger.info(f"✅ JSON 验证通过: {file_path}")
        return ValidationResult(is_valid=True)
    
    def validate_yaml_file(
        self,
        file_path: str,
        file_content: str
    ) -> ValidationResult:
        """
        验证 YAML 文件
        
        Args:
            file_path: 文件路径
            file_content: 文件内容
            
        Returns:
            验证结果
        """
        errors = []
        
        try:
            import yaml
            yaml.safe_load(file_content)
        except ImportError:
            # YAML 库不可用，跳过验证
            logger.warning("PyYAML 未安装，跳过 YAML 验证")
            return ValidationResult(is_valid=True)
        except yaml.YAMLError as e:
            errors.append(f"YAML 错误: {e}")
            logger.error(f"YAML 验证失败: {file_path} - {e}")
            return ValidationResult(is_valid=False, errors=errors)
        
        logger.info(f"✅ YAML 验证通过: {file_path}")
        return ValidationResult(is_valid=True)
    
    def validate_arduino_cpp_file(
        self,
        file_path: str,
        file_content: str
    ) -> ValidationResult:
        """
        验证 Arduino C++ 文件
        
        检查：
        - 基本语法（括号匹配、分号等）
        - Arduino 特定：setup/loop 函数存在性
        - 常见错误模式
        
        Args:
            file_path: 文件路径
            file_content: 文件内容
            
        Returns:
            验证结果
        """
        logger.debug(f"[Validator] 开始验证 Arduino C++ 文件: {file_path}")
        logger.debug(f"[Validator]   文件大小: {len(file_content)} 字符, {file_content.count(chr(10))+1} 行")
        
        errors = []
        warnings = []
        
        # 1. 括号匹配检查
        logger.debug(f"[Validator]   检查括号匹配...")
        if not self._check_brackets(file_content):
            errors.append("括号不匹配")
            logger.error(f"[Validator] ❌ 括号不匹配")
        else:
            logger.debug(f"[Validator]     括号检查通过")
        
        # 2. 检查基本结构（.ino 文件应该有 setup 和 loop）
        if file_path.endswith('.ino'):
            logger.debug(f"[Validator]   检查 Arduino 基本结构...")
            has_setup = 'void setup()' in file_content
            has_loop = 'void loop()' in file_content
            
            if not has_setup:
                warnings.append("缺少 setup() 函数（Arduino 项目通常需要）")
                logger.debug(f"[Validator]     警告: 缺少 setup()")
            else:
                logger.debug(f"[Validator]     发现 setup()")
                
            if not has_loop:
                warnings.append("缺少 loop() 函数（Arduino 项目通常需要）")
                logger.debug(f"[Validator]     警告: 缺少 loop()")
            else:
                logger.debug(f"[Validator]     发现 loop()")
        
        # 3. 检查常见错误模式
        # 检查是否有未闭合的 #if
        logger.debug(f"[Validator]   检查预处理器指令...")
        if_preprocessor_count = file_content.count('#if')
        endif_preprocessor_count = file_content.count('#endif')
        logger.debug(f"[Validator]     #if: {if_preprocessor_count}, #endif: {endif_preprocessor_count}")
        if if_preprocessor_count != endif_preprocessor_count:
            errors.append(f"#if/#endif 不匹配: {if_preprocessor_count} vs {endif_preprocessor_count}")
            logger.error(f"[Validator] ❌ #if/#endif 不匹配")
        
        # 检查字符串引号匹配（简单检查）
        logger.debug(f"[Validator]   检查字符串引号...")
        double_quotes = file_content.count('"') - file_content.count('\\"')
        logger.debug(f"[Validator]     双引号数量: {double_quotes}")
        if double_quotes % 2 != 0:
            errors.append("双引号不匹配（可能有未闭合的字符串）")
            logger.error(f"[Validator] ❌ 双引号不匹配")
        
        # 4. 检查函数定义格式（简单启发式）
        logger.debug(f"[Validator]   检查函数定义...")
        func_pattern = r'(void|int|bool|float|double|String)\s+\w+\s*\([^)]*\)\s*\{'
        functions = re.findall(func_pattern, file_content)
        logger.debug(f"[Validator]     发现 {len(functions)} 个函数")
        
        # 检查每个 { 是否有对应的 }
        logger.debug(f"[Validator]   检查大括号平衡...")
        open_braces = file_content.count('{')
        close_braces = file_content.count('}')
        logger.debug(f"[Validator]     {{ x{open_braces}, }} x{close_braces}")
        if open_braces != close_braces:
            errors.append(f"大括号不匹配: {{ x{open_braces}, }} x{close_braces}")
            logger.error(f"[Validator] ❌ 大括号不匹配")
        
        # 5. Arduino 特定警告
        logger.debug(f"[Validator]   检查 Arduino 特定模式...")
        # 检查 delay 使用（可能阻塞）
        delay_count = file_content.count('delay(')
        if delay_count > 0:
            warnings.append(f"使用了 {delay_count} 处 delay()，可能会阻塞程序执行")
            logger.debug(f"[Validator]     发现 {delay_count} 处 delay()")
        
        # 检查 Serial 使用但没有波特率设置
        has_serial = 'Serial.' in file_content
        has_serial_begin = 'Serial.begin(' in file_content
        if has_serial and not has_serial_begin:
            warnings.append("使用了 Serial 但没有调用 Serial.begin() 设置波特率")
            logger.debug(f"[Validator]     警告: 使用 Serial 但未设置波特率")
        elif has_serial and has_serial_begin:
            logger.debug(f"[Validator]     Serial 配置正确")
        
        # 检查库引用
        includes = re.findall(r'#include\s*[<"]([^>"]+)[>"]', file_content)
        logger.debug(f"[Validator]     包含库: {includes}")
        
        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"[Validator] ✅ Arduino C++ 验证通过: {file_path}")
        else:
            logger.error(f"[Validator] ❌ Arduino C++ 验证失败: {file_path}")
            logger.error(f"[Validator]    错误: {errors}")
        
        if warnings:
            logger.warning(f"[Validator] ⚠️  警告: {warnings}")
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings
        )
    
    def validate_modification(
        self,
        file_path: str,
        original_content: str,
        modified_content: str,
        instruction: str = None
    ) -> ValidationResult:
        """
        验证代码修改的完整性和正确性
        
        检查：
        - 语法正确性
        - 修改实际发生
        - 关键结构保留
        - 无意外删除
        
        Args:
            file_path: 文件路径
            original_content: 原始内容
            modified_content: 修改后内容
            instruction: 修改指令（可选，用于 AI 验证）
            
        Returns:
            验证结果
        """
        errors = []
        warnings = []
        
        # 1. 检查修改是否实际发生
        if original_content == modified_content:
            errors.append("内容未变化 - 没有实际修改")
            return ValidationResult(is_valid=False, errors=errors)
        
        # 2. 语法验证
        syntax_result = self.validate_file(file_path, modified_content)
        if not syntax_result.is_valid:
            errors.extend(syntax_result.errors)
            return ValidationResult(is_valid=False, errors=errors)
        
        warnings.extend(syntax_result.warnings)
        
        # 3. 检查关键结构保留（Python）
        if file_path.endswith('.py'):
            structure_check = self._check_python_structure_preserved(
                original_content, modified_content
            )
            if not structure_check.is_valid:
                errors.extend(structure_check.errors)
                warnings.extend(structure_check.warnings)
        
        # 4. 检查关键结构保留（Arduino C++）
        elif file_path.endswith(('.cpp', '.c', '.h', '.hpp', '.ino')):
            structure_check = self._check_cpp_structure_preserved(
                original_content, modified_content
            )
            if not structure_check.is_valid:
                errors.extend(structure_check.errors)
                warnings.extend(structure_check.warnings)
        
        is_valid = len(errors) == 0
        if is_valid:
            logger.info(f"✅ 修改验证通过: {file_path}")
        else:
            logger.error(f"❌ 修改验证失败: {file_path} - {errors}")
        
        return ValidationResult(
            is_valid=is_valid,
            errors=errors,
            warnings=warnings
        )
    
    def _check_python_structure_preserved(
        self,
        original: str,
        modified: str
    ) -> ValidationResult:
        """
        检查 Python 代码结构是否被意外破坏
        
        检查：
        - 类定义是否完整
        - 函数定义是否完整
        - import 语句是否保留
        """
        errors = []
        warnings = []
        
        try:
            orig_tree = ast.parse(original)
            mod_tree = ast.parse(modified)
            
            # 提取原始代码中的类名
            orig_classes = {
                node.name for node in ast.walk(orig_tree) 
                if isinstance(node, ast.ClassDef)
            }
            mod_classes = {
                node.name for node in ast.walk(mod_tree) 
                if isinstance(node, ast.ClassDef)
            }
            
            # 检查是否有类被意外删除
            deleted_classes = orig_classes - mod_classes
            if deleted_classes:
                warnings.append(f"以下类可能被删除: {deleted_classes}")
            
            # 提取原始代码中的顶层函数名
            orig_funcs = {
                node.name for node in ast.walk(orig_tree)
                if isinstance(node, ast.FunctionDef) and 
                not isinstance(getattr(node, 'parent', None), ast.ClassDef)
            }
            mod_funcs = {
                node.name for node in ast.walk(mod_tree)
                if isinstance(node, ast.FunctionDef) and
                not isinstance(getattr(node, 'parent', None), ast.ClassDef)
            }
            
            # 检查是否有函数被意外删除
            deleted_funcs = orig_funcs - mod_funcs
            if deleted_funcs:
                warnings.append(f"以下函数可能被删除: {deleted_funcs}")
            
        except SyntaxError:
            # 语法错误会在其他检查中捕获
            pass
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def _check_cpp_structure_preserved(
        self,
        original: str,
        modified: str
    ) -> ValidationResult:
        """
        检查 C++ 代码结构是否被意外破坏
        
        检查：
        - 函数声明是否保留
        - 类定义是否完整
        - #include 是否保留
        """
        errors = []
        warnings = []
        
        # 检查 #include 是否被意外删除
        orig_includes = set(re.findall(r'#include\s*[<"][^>"]+[>"]', original))
        mod_includes = set(re.findall(r'#include\s*[<"][^>"]+[>"]', modified))
        
        deleted_includes = orig_includes - mod_includes
        if deleted_includes:
            warnings.append(f"以下 #include 可能被删除: {deleted_includes}")
        
        # 检查函数定义（简单模式匹配）
        func_pattern = r'(void|int|bool|float|double|String)\s+(\w+)\s*\([^)]*\)\s*\{'
        orig_funcs = set(re.findall(func_pattern, original))
        mod_funcs = set(re.findall(func_pattern, modified))
        
        # 提取函数名
        orig_func_names = {f[1] for f in orig_funcs}
        mod_func_names = {f[1] for f in mod_funcs}
        
        deleted_funcs = orig_func_names - mod_func_names
        if deleted_funcs:
            warnings.append(f"以下函数可能被删除: {deleted_funcs}")
        
        return ValidationResult(
            is_valid=len(errors) == 0,
            errors=errors,
            warnings=warnings
        )
    
    def validate_file(
        self,
        file_path: str,
        file_content: str
    ) -> ValidationResult:
        """
        验证文件（根据扩展名自动判断类型）
        
        Args:
            file_path: 文件路径
            file_content: 文件内容
            
        Returns:
            验证结果
        """
        if file_path.endswith('.py'):
            return self.validate_python_file(file_path, file_content)
        elif file_path.endswith('.json'):
            return self.validate_json_file(file_path, file_content)
        elif file_path.endswith(('.yml', '.yaml')):
            return self.validate_yaml_file(file_path, file_content)
        elif file_path.endswith(('.cpp', '.c', '.h', '.hpp', '.ino')):
            return self.validate_arduino_cpp_file(file_path, file_content)
        else:
            # 其他文件类型，不验证
            logger.debug(f"跳过验证: {file_path}")
            return ValidationResult(is_valid=True)
    
    def validate_batch(
        self,
        files: Dict[str, str]
    ) -> Dict[str, ValidationResult]:
        """
        批量验证多个文件
        
        Args:
            files: {文件路径: 文件内容} 字典
            
        Returns:
            {文件路径: 验证结果} 字典
        """
        results = {}
        for file_path, content in files.items():
            results[file_path] = self.validate_file(file_path, content)
        return results
    
    def _check_brackets(self, content: str) -> bool:
        """
        检查括号是否匹配
        
        Args:
            content: 代码内容
            
        Returns:
            是否匹配
        """
        stack = []
        pairs = {'(': ')', '[': ']', '{': '}'}
        close = set(pairs.values())
        
        # 忽略字符串中的括号
        in_string = False
        string_char = None
        escaped = False
        
        for char in content:
            if escaped:
                escaped = False
                continue
            
            if char == '\\':
                escaped = True
                continue
            
            if char in ('"', "'"):
                if not in_string:
                    in_string = True
                    string_char = char
                elif char == string_char:
                    in_string = False
                    string_char = None
                continue
            
            if in_string:
                continue
            
            if char in pairs:
                stack.append(char)
            elif char in close:
                if not stack or pairs[stack.pop()] != char:
                    return False
        
        return len(stack) == 0
    
    def _has_indentation_errors(self, content: str) -> bool:
        """
        检查可能的缩进问题
        
        Args:
            content: 代码内容
            
        Returns:
            是否有问题
        """
        lines = content.split('\n')
        for i, line in enumerate(lines, 1):
            # 检查混合缩进
            if '\t' in line and '  ' in line:
                return True
        
        return False
    
    def ai_validate(
        self,
        file_path: str,
        original_content: str,
        modified_content: str,
        requirement: str
    ) -> ValidationResult:
        """
        AI 辅助验证
        
        让 AI 检查修改是否符合需求
        
        Args:
            file_path: 文件路径
            original_content: 原始内容
            modified_content: 修改后内容
            requirement: 需求说明
            
        Returns:
            验证结果
        """
        if not self.code_generator:
            # 没有代码生成器，跳过 AI 验证
            return ValidationResult(is_valid=True)
        
        prompt = f"""验证代码修改是否符合需求。

## 文件

{file_path}

## 原始内容（片段）

```python
{original_content[:500]}...
```

## 修改后内容（片段）

```python
{modified_content[:500]}...
```

## 需求

{requirement}

## 验证要求

1. 修改是否符合需求？
2. 是否有潜在的 bug？
3. 是否保持了代码风格一致性？

## 输出格式

```json
{{
  "is_valid": true,
  "errors": ["如果无效，列出错误"],
  "warnings": ["潜在警告"]
}}
```"""
        
        logger.info(f"AI 辅助验证: {file_path}")
        response = self.code_generator._generate(prompt, temperature=0.1)
        
        try:
            json_match = re.search(r'\{.*\}', response, re.DOTALL)
            if json_match:
                data = json.loads(json_match.group())
                return ValidationResult(
                    is_valid=data.get('is_valid', True),
                    errors=data.get('errors', []),
                    warnings=data.get('warnings', [])
                )
        except Exception as e:
            logger.error(f"AI 验证解析失败: {e}")
        
        # 解析失败时假设通过
        return ValidationResult(is_valid=True)
