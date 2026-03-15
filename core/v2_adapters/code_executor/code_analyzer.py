#!/usr/bin/env python3
"""
代码分析器 - 理解 Python 和 Arduino C++ 代码结构

提供能力：
1. 从 Issue 描述中提取关键词（函数名、类名、错误信息）
2. 分析代码依赖关系（函数调用、全局变量、库依赖）
3. Arduino 特定分析（引脚使用、中断、库依赖）
4. 智能选择需要修改的文件

利用 256K 上下文窗口，可以分析整个小型项目
"""

import re
import ast
from core.logging import get_logger
from pathlib import Path
from typing import Dict, List, Set, Tuple, Optional, Any
from dataclasses import dataclass, field

logger = get_logger(__name__)


@dataclass
class FunctionInfo:
    """函数信息"""
    name: str
    line_start: int
    line_end: int
    params: List[str]
    calls: Set[str] = field(default_factory=set)
    called_by: Set[str] = field(default_factory=set)


@dataclass
class VariableInfo:
    """变量信息"""
    name: str
    line: int
    var_type: str  # "global", "local", "param"
    data_type: Optional[str] = None


@dataclass
class ArduinoPinInfo:
    """Arduino 引脚使用信息"""
    pin_number: int
    mode: str  # "INPUT", "OUTPUT", "INPUT_PULLUP"
    operations: List[str] = field(default_factory=list)  # "digitalWrite", "analogRead" 等
    line: int = 0


@dataclass
class FileAnalysis:
    """单个文件的分析结果"""
    path: str
    language: str  # "python", "cpp", "arduino"
    functions: Dict[str, FunctionInfo] = field(default_factory=dict)
    variables: Dict[str, VariableInfo] = field(default_factory=dict)
    includes: List[str] = field(default_factory=list)
    # Arduino 特定
    pins: Dict[int, ArduinoPinInfo] = field(default_factory=dict)
    libraries: List[str] = field(default_factory=list)
    interrupts: List[Dict] = field(default_factory=list)


@dataclass
class DependencyGraph:
    """跨文件依赖图"""
    files: Dict[str, FileAnalysis] = field(default_factory=dict)
    call_graph: Dict[str, Set[str]] = field(default_factory=dict)  # func -> {called_funcs}
    global_vars: Dict[str, List[str]] = field(default_factory=dict)  # var -> [files_using_it]


class CodeAnalyzer:
    """
    代码分析器
    
    支持 Python 和 Arduino C++ 代码分析
    利用 256K 上下文可以进行跨文件依赖分析
    """
    
    def __init__(self):
        self.logger = get_logger(__name__)
    
    # ============================================================================
    # 入口方法
    # ============================================================================
    
    def analyze_for_issue(
        self,
        repo_path: Path,
        issue_title: str,
        issue_body: str,
        files_to_analyze: Optional[List[str]] = None
    ) -> Tuple[List[str], DependencyGraph, str]:
        """
        分析 Issue 并确定需要修改的文件
        
        Args:
            repo_path: 仓库本地路径
            issue_title: Issue 标题
            issue_body: Issue 内容
            files_to_analyze: 指定分析的文件列表，None 则自动发现
            
        Returns:
            (files_to_modify, dependency_graph, analysis_reasoning)
            - files_to_modify: 建议修改的文件列表
            - dependency_graph: 完整的依赖分析结果
            - analysis_reasoning: 分析推理说明
        """
        self.logger.info(f"[CodeAnalyzer] 开始分析 Issue: {issue_title[:80]}...")
        self.logger.debug(f"[CodeAnalyzer] Issue 完整标题: {issue_title}")
        self.logger.debug(f"[CodeAnalyzer] Issue 内容长度: {len(issue_body)} 字符")
        
        # 1. 提取 Issue 中的关键词
        self.logger.debug("[CodeAnalyzer] Step 1: 提取关键词...")
        keywords = self._extract_keywords(issue_title, issue_body)
        self.logger.info(f"[CodeAnalyzer] 提取关键词: {keywords}")
        
        # 2. 发现代码文件
        self.logger.debug("[CodeAnalyzer] Step 2: 发现代码文件...")
        if files_to_analyze is None:
            files_to_analyze = self._discover_code_files(repo_path)
        self.logger.info(f"[CodeAnalyzer] 发现 {len(files_to_analyze)} 个代码文件")
        self.logger.debug(f"[CodeAnalyzer] 文件列表: {files_to_analyze}")
        
        # 3. 分析所有相关文件
        self.logger.debug("[CodeAnalyzer] Step 3: 分析文件结构...")
        graph = DependencyGraph()
        analyzed_count = 0
        for file_path in files_to_analyze:
            full_path = repo_path / file_path
            if not full_path.exists():
                self.logger.debug(f"[CodeAnalyzer] 文件不存在，跳过: {file_path}")
                continue
                
            try:
                self.logger.debug(f"[CodeAnalyzer] 分析文件: {file_path}")
                analysis = self._analyze_single_file(full_path)
                if analysis:
                    graph.files[file_path] = analysis
                    analyzed_count += 1
                    self.logger.debug(f"[CodeAnalyzer]   - 语言: {analysis.language}")
                    self.logger.debug(f"[CodeAnalyzer]   - 函数: {list(analysis.functions.keys())}")
                    self.logger.debug(f"[CodeAnalyzer]   - 引脚: {list(analysis.pins.keys())}")
                    self.logger.debug(f"[CodeAnalyzer]   - 库: {analysis.libraries}")
            except Exception as e:
                self.logger.warning(f"[CodeAnalyzer] 分析文件失败 {file_path}: {e}", exc_info=True)
        
        self.logger.info(f"[CodeAnalyzer] 成功分析 {analyzed_count}/{len(files_to_analyze)} 个文件")
        
        # 4. 构建跨文件依赖关系
        self.logger.debug("[CodeAnalyzer] Step 4: 构建跨文件依赖关系...")
        self._build_cross_file_dependencies(graph)
        self.logger.debug(f"[CodeAnalyzer] 全局变量依赖: {len(graph.global_vars)} 个")
        self.logger.debug(f"[CodeAnalyzer] 函数调用关系: {len(graph.call_graph)} 条")
        
        # 5. 根据 Issue 关键词匹配相关文件
        self.logger.debug("[CodeAnalyzer] Step 5: 匹配相关文件...")
        files_to_modify = self._match_files_to_issue(graph, keywords, issue_body)
        self.logger.info(f"[CodeAnalyzer] 匹配到 {len(files_to_modify)} 个待修改文件: {files_to_modify}")
        
        # 6. 生成分析说明
        self.logger.debug("[CodeAnalyzer] Step 6: 生成分析说明...")
        reasoning = self._generate_reasoning(files_to_modify, keywords, graph)
        self.logger.debug(f"[CodeAnalyzer] 分析说明长度: {len(reasoning)} 字符")
        
        self.logger.info("[CodeAnalyzer] Issue 分析完成")
        return files_to_modify, graph, reasoning
    
    # ============================================================================
    # 关键词提取
    # ============================================================================
    
    def _extract_keywords(self, title: str, body: str) -> Dict[str, List[str]]:
        """
        从 Issue 中提取关键信息
        
        Returns:
            {
                "functions": ["func1", "func2"],
                "classes": ["ClassA"],
                "variables": ["max_count"],
                "error_messages": ["Index out of range"],
                "files": ["main.py"],
                "arduino_pins": [13, "A0"],
                "libraries": ["Wire"]
            }
        """
        text = f"{title}\n{body}"
        keywords = {
            "functions": [],
            "classes": [],
            "variables": [],
            "error_messages": [],
            "files": [],
            "arduino_pins": [],
            "libraries": []
        }
        
        # 提取错误信息（通常是引号中的内容）
        error_patterns = [
            r'["\']([^"\']*error[^"\']*)["\']',
            r'["\']([^"\']*exception[^"\']*)["\']',
            r'["\']([^"\']*fail[^"\']*)["\']',
        ]
        for pattern in error_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            keywords["error_messages"].extend(matches)
        
        # 提取文件引用（xxx.py, xxx.cpp, xxx.ino）
        file_pattern = r'\b([\w_]+\.(?:py|cpp|c|h|hpp|ino))\b'
        keywords["files"] = list(set(re.findall(file_pattern, text)))
        
        # 提取引用的函数名（`function_name` 或 "function_name"）
        func_pattern = r'[`"\']([a-z_][a-z0-9_]*)\s*\([^`"\']*\)[`"\']'
        keywords["functions"] = list(set(re.findall(func_pattern, text, re.IGNORECASE)))
        
        # 提取 Arduino 引脚引用（pin 13, digital pin 5, A0 等）
        pin_patterns = [
            r'(?:pin|analog)\s*[=:]?\s*(A\d+)',  # pin A0, analog A0, pin=A0
            r'(?:pin|digital|gpio)\s*[=:]?\s*(\d+)',  # pin 13, digital 5
            r'analogRead\s*\(\s*(A\d+)\s*\)',  # analogRead(A0)
            r'\banalog\s+(pin\s+)?(A\d+)\b',  # analog pin A0
            r'\b(A\d+)\b',  # A0, A1 等（最后尝试）
        ]
        for pattern in pin_patterns:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if isinstance(match, tuple):
                    # 取非空的组
                    pin = next((m for m in match if m), None)
                    if pin:
                        keywords["arduino_pins"].append(pin)
                else:
                    keywords["arduino_pins"].append(match)
        
        # 提取库引用
        # 1. #include <Library> 格式
        lib_pattern = r'#include\s*[<"]([\w_]+)[>"]'
        keywords["libraries"].extend(re.findall(lib_pattern, text))
        
        # 2. 常见 Arduino 库名称直接匹配
        common_arduino_libs = [
            "Wire", "SPI", "EEPROM", "SoftwareSerial", "Servo", "Stepper",
            "Ethernet", "WiFi", "SD", "TFT", "Esplora", "OneWire",
            "DallasTemperature", "DHT", "Adafruit", "NeoPixel", "FastLED"
        ]
        for lib in common_arduino_libs:
            if re.search(rf'\b{lib}\b', text, re.IGNORECASE):
                keywords["libraries"].append(lib)
        
        # 清理和去重
        for key in keywords:
            keywords[key] = list(set(k for k in keywords[key] if k))
        
        return keywords
    
    # ============================================================================
    # 文件分析
    # ============================================================================
    
    def _analyze_single_file(self, file_path: Path) -> Optional[FileAnalysis]:
        """分析单个文件"""
        try:
            content = file_path.read_text(encoding='utf-8', errors='ignore')
        except Exception as e:
            self.logger.warning(f"无法读取文件 {file_path}: {e}")
            return None
        
        suffix = file_path.suffix.lower()
        
        if suffix == '.py':
            return self._analyze_python_file(str(file_path.relative_to(file_path.parent.parent)), content)
        elif suffix in ['.cpp', '.c', '.h', '.hpp', '.ino']:
            return self._analyze_arduino_cpp_file(str(file_path.relative_to(file_path.parent.parent)), content)
        else:
            return None
    
    def _analyze_python_file(self, path: str, content: str) -> FileAnalysis:
        """分析 Python 文件"""
        analysis = FileAnalysis(path=path, language="python")
        
        try:
            tree = ast.parse(content)
        except SyntaxError as e:
            self.logger.warning(f"Python 语法错误 {path}: {e}")
            # 继续用正则分析
            return self._analyze_python_with_regex(path, content)
        
        # 遍历 AST
        for node in ast.walk(tree):
            if isinstance(node, ast.FunctionDef):
                func_info = FunctionInfo(
                    name=node.name,
                    line_start=node.lineno,
                    line_end=node.end_lineno if hasattr(node, 'end_lineno') else node.lineno,
                    params=[arg.arg for arg in node.args.args]
                )
                
                # 查找函数内的调用
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        if isinstance(child.func, ast.Name):
                            func_info.calls.add(child.func.id)
                        elif isinstance(child.func, ast.Attribute):
                            func_info.calls.add(child.func.attr)
                
                analysis.functions[node.name] = func_info
            
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    analysis.includes.append(alias.name)
            
            elif isinstance(node, ast.ImportFrom):
                analysis.includes.append(node.module)
        
        return analysis
    
    def _analyze_python_with_regex(self, path: str, content: str) -> FileAnalysis:
        """用正则分析 Python（当 AST 解析失败时）"""
        analysis = FileAnalysis(path=path, language="python")
        
        # 提取函数定义
        func_pattern = r'^def\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)'
        for match in re.finditer(func_pattern, content, re.MULTILINE):
            func_name = match.group(1)
            params = [p.strip() for p in match.group(2).split(',') if p.strip()]
            line_num = content[:match.start()].count('\n') + 1
            
            analysis.functions[func_name] = FunctionInfo(
                name=func_name,
                line_start=line_num,
                line_end=line_num,  # 暂时不知道结束行
                params=params
            )
        
        # 提取 import
        import_pattern = r'^(?:from|import)\s+([\w.]+)'
        for match in re.finditer(import_pattern, content, re.MULTILINE):
            analysis.includes.append(match.group(1))
        
        return analysis
    
    def _analyze_arduino_cpp_file(self, path: str, content: str) -> FileAnalysis:
        """分析 Arduino C++ 文件"""
        analysis = FileAnalysis(path=path, language="arduino")
        
        # 1. 提取库依赖
        include_pattern = r'#include\s*[<"]([^>"]+)[>"]'
        analysis.includes = re.findall(include_pattern, content)
        analysis.libraries = [inc.replace('.h', '') for inc in analysis.includes 
                             if not inc.startswith('/')]
        
        # 2. 提取函数定义（C++ 风格）
        # 匹配: void setup(), int readSensor(), 等
        func_pattern = r'^(\w+[\w\s:*&]*)\s+([a-zA-Z_][a-zA-Z0-9_]*)\s*\(([^)]*)\)\s*\{'
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            match = re.match(func_pattern, line.strip())
            if match:
                return_type = match.group(1).strip()
                func_name = match.group(2)
                params_str = match.group(3)
                params = [p.strip().split()[-1] if ' ' in p else p 
                         for p in params_str.split(',') if p.strip()]
                
                # 找到函数结束行（简单方法：匹配大括号）
                line_start = i + 1
                line_end = self._find_function_end(lines, i)
                
                analysis.functions[func_name] = FunctionInfo(
                    name=func_name,
                    line_start=line_start,
                    line_end=line_end,
                    params=params
                )
        
        # 3. 提取引脚使用
        analysis.pins = self._extract_arduino_pins(content)
        
        # 4. 提取中断使用
        analysis.interrupts = self._extract_interrupts(content)
        
        # 5. 提取全局变量（简单方法）
        analysis.variables = self._extract_cpp_globals(content)
        
        return analysis
    
    def _extract_arduino_pins(self, content: str) -> Dict[int, ArduinoPinInfo]:
        """提取 Arduino 引脚使用情况"""
        pins = {}
        lines = content.split('\n')
        
        # 首先提取 #define 宏定义（如 #define SENSOR_PIN A0）
        pin_macros = {}
        for line in lines:
            macro_match = re.search(r'#define\s+(\w+)\s+(A\d+|\d+)', line)
            if macro_match:
                macro_name = macro_match.group(1)
                pin_value = macro_match.group(2)
                pin_macros[macro_name] = pin_value
        
        for i, line in enumerate(lines):
            # pinMode(pin, mode) - 支持数字、A0、或宏
            pinmode_match = re.search(r'pinMode\s*\(\s*(\w+)\s*,\s*(\w+)\s*\)', line)
            if pinmode_match:
                pin_str = pinmode_match.group(1)
                mode = pinmode_match.group(2)
                
                # 解析引脚号（处理宏）
                pin_num = self._resolve_pin_number(pin_str, pin_macros)
                if pin_num is not None:
                    if pin_num not in pins:
                        pins[pin_num] = ArduinoPinInfo(pin_number=pin_num, mode=mode, line=i+1)
                    else:
                        pins[pin_num].mode = mode
            
            # digitalWrite(pin, value)
            dw_match = re.search(r'digitalWrite\s*\(\s*(\w+)\s*,', line)
            if dw_match:
                pin_str = dw_match.group(1)
                pin_num = self._resolve_pin_number(pin_str, pin_macros)
                if pin_num is not None:
                    if pin_num not in pins:
                        pins[pin_num] = ArduinoPinInfo(pin_number=pin_num, mode="UNKNOWN", line=i+1)
                    pins[pin_num].operations.append("digitalWrite")
            
            # digitalRead(pin)
            dr_match = re.search(r'digitalRead\s*\(\s*(\w+)\s*\)', line)
            if dr_match:
                pin_str = dr_match.group(1)
                pin_num = self._resolve_pin_number(pin_str, pin_macros)
                if pin_num is not None:
                    if pin_num not in pins:
                        pins[pin_num] = ArduinoPinInfo(pin_number=pin_num, mode="UNKNOWN", line=i+1)
                    pins[pin_num].operations.append("digitalRead")
            
            # analogRead(pin)
            ar_match = re.search(r'analogRead\s*\(\s*(\w+)\s*\)', line)
            if ar_match:
                pin_str = ar_match.group(1)
                pin_num = self._resolve_pin_number(pin_str, pin_macros)
                if pin_num is not None:
                    if pin_num not in pins:
                        pins[pin_num] = ArduinoPinInfo(pin_number=pin_num, mode="INPUT", line=i+1)
                    pins[pin_num].operations.append("analogRead")
            
            # analogWrite(pin, value) - PWM
            aw_match = re.search(r'analogWrite\s*\(\s*(\w+)\s*,', line)
            if aw_match:
                pin_str = aw_match.group(1)
                pin_num = self._resolve_pin_number(pin_str, pin_macros)
                if pin_num is not None:
                    if pin_num not in pins:
                        pins[pin_num] = ArduinoPinInfo(pin_number=pin_num, mode="OUTPUT", line=i+1)
                    pins[pin_num].operations.append("analogWrite")
        
        return pins
    
    def _resolve_pin_number(self, pin_str: str, pin_macros: Dict[str, str]) -> Optional[int]:
        """
        解析引脚号，支持宏定义
        
        Args:
            pin_str: 引脚字符串（如 "A0", "13", "SENSOR_PIN"）
            pin_macros: 宏定义字典（如 {"SENSOR_PIN": "A0"}）
            
        Returns:
            引脚数字，无法解析返回 None
        """
        # 直接是数字
        if pin_str.isdigit():
            return int(pin_str)
        
        # 直接是 A0, A1 等
        if pin_str.startswith('A') and pin_str[1:].isdigit():
            return int(pin_str[1:]) + 14  # A0 = 14, A1 = 15, ...
        
        # 查找宏定义
        if pin_str in pin_macros:
            macro_value = pin_macros[pin_str]
            return self._resolve_pin_number(macro_value, {})  # 递归解析
        
        # 无法解析（可能是变量或表达式）
        return None
    
    def _extract_interrupts(self, content: str) -> List[Dict]:
        """提取中断配置"""
        interrupts = []
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            # attachInterrupt(digitalPinToInterrupt(pin), ISR, mode)
            match = re.search(r'attachInterrupt\s*\([^,]+,\s*(\w+)\s*,\s*(\w+)\s*\)', line)
            if match:
                interrupts.append({
                    "isr_function": match.group(1),
                    "mode": match.group(2),
                    "line": i + 1
                })
        
        return interrupts
    
    def _extract_cpp_globals(self, content: str) -> Dict[str, VariableInfo]:
        """提取 C++ 全局变量（简单实现）"""
        globals = {}
        lines = content.split('\n')
        
        for i, line in enumerate(lines):
            # 匹配: int x;, const float Y = 1.0;, 等
            # 跳过函数内的变量（简单判断：行首缩进）
            if line.startswith(' ') or line.startswith('\t'):
                continue
            
            match = re.match(r'^(const\s+)?(\w+)\s+(\w+)\s*[=;]', line.strip())
            if match:
                var_type = "global"
                data_type = match.group(2)
                var_name = match.group(3)
                globals[var_name] = VariableInfo(
                    name=var_name,
                    line=i+1,
                    var_type=var_type,
                    data_type=data_type
                )
        
        return globals
    
    def _find_function_end(self, lines: List[str], start_idx: int) -> int:
        """找到函数结束行（简单的大括号匹配）"""
        brace_count = 0
        started = False
        
        for i in range(start_idx, len(lines)):
            line = lines[i]
            for char in line:
                if char == '{':
                    brace_count += 1
                    started = True
                elif char == '}':
                    brace_count -= 1
                    if started and brace_count == 0:
                        return i + 1
        
        return start_idx + 1
    
    # ============================================================================
    # 依赖分析
    # ============================================================================
    
    def _build_cross_file_dependencies(self, graph: DependencyGraph):
        """构建跨文件依赖关系"""
        # 1. 构建全局变量使用图
        all_globals = {}
        for file_path, analysis in graph.files.items():
            for var_name in analysis.variables:
                if var_name not in all_globals:
                    all_globals[var_name] = []
                all_globals[var_name].append(file_path)
        
        graph.global_vars = all_globals
        
        # 2. 构建函数调用图（跨文件）
        all_functions = set()
        for analysis in graph.files.values():
            all_functions.update(analysis.functions.keys())
        
        for file_path, analysis in graph.files.items():
            for func_name, func_info in analysis.functions.items():
                for called in func_info.calls:
                    # 如果被调用的函数在其他文件中定义
                    for other_path, other_analysis in graph.files.items():
                        if other_path != file_path and called in other_analysis.functions:
                            key = f"{file_path}::{func_name}"
                            if key not in graph.call_graph:
                                graph.call_graph[key] = set()
                            graph.call_graph[key].add(f"{other_path}::{called}")
    
    # ============================================================================
    # 文件匹配
    # ============================================================================
    
    def _match_files_to_issue(
        self,
        graph: DependencyGraph,
        keywords: Dict[str, List[str]],
        issue_body: str
    ) -> List[str]:
        """
        根据 Issue 关键词匹配相关文件
        
        返回按相关性排序的文件列表
        """
        file_scores = {}
        
        for file_path, analysis in graph.files.items():
            score = 0
            reasons = []
            
            # 1. 文件名匹配（Issue 中明确提到的文件）
            for mentioned_file in keywords["files"]:
                if mentioned_file.lower() in file_path.lower():
                    score += 100
                    reasons.append(f"文件名被提及: {mentioned_file}")
            
            # 2. 函数名匹配
            for func in keywords["functions"]:
                if func in analysis.functions:
                    score += 50
                    reasons.append(f"包含函数: {func}")
                # 函数被调用
                for f in analysis.functions.values():
                    if func in f.calls:
                        score += 30
                        reasons.append(f"调用函数: {func}")
            
            # 3. Arduino 引脚匹配
            for pin in keywords["arduino_pins"]:
                try:
                    pin_num = int(pin[1:]) + 14 if pin.startswith('A') else int(pin)
                    if pin_num in analysis.pins:
                        score += 40
                        reasons.append(f"使用引脚: {pin}")
                except ValueError:
                    pass
            
            # 4. 库依赖匹配
            for lib in keywords["libraries"]:
                if lib in analysis.libraries:
                    score += 20
                    reasons.append(f"使用库: {lib}")
            
            # 5. 错误信息内容匹配（简单字符串匹配）
            if analysis.language == "python":
                # 提取错误中的函数名或变量名
                for error in keywords["error_messages"]:
                    words = re.findall(r'\b[a-z_][a-z0-9_]*\b', error.lower())
                    for word in words:
                        if word in analysis.functions:
                            score += 25
                            reasons.append(f"错误相关函数: {word}")
                        if word in analysis.variables:
                            score += 20
                            reasons.append(f"错误相关变量: {word}")
            
            if score > 0:
                file_scores[file_path] = (score, reasons)
        
        # 按分数排序
        sorted_files = sorted(file_scores.items(), key=lambda x: x[1][0], reverse=True)
        
        # 返回前 N 个文件
        max_files = 5  # 限制修改文件数量
        selected_files = [f[0] for f in sorted_files[:max_files]]
        
        self.logger.info(f"匹配到的文件: {selected_files}")
        for f, (score, reasons) in sorted_files[:max_files]:
            self.logger.info(f"  {f}: score={score}, reasons={reasons}")
        
        return selected_files
    
    def _generate_reasoning(
        self,
        files_to_modify: List[str],
        keywords: Dict[str, List[str]],
        graph: DependencyGraph
    ) -> str:
        """生成分析说明"""
        reasoning = f"""## 代码分析结果

### 提取的关键词
- 函数: {', '.join(keywords['functions']) or '无'}
- 类/变量: {', '.join(keywords['variables']) or '无'}
- Arduino 引脚: {', '.join(keywords['arduino_pins']) or '无'}
- 库: {', '.join(keywords['libraries']) or '无'}

### 建议修改的文件
"""
        for file_path in files_to_modify:
            analysis = graph.files.get(file_path)
            if analysis:
                reasoning += f"\n**{file_path}**\n"
                reasoning += f"- 语言: {analysis.language}\n"
                reasoning += f"- 函数: {list(analysis.functions.keys())}\n"
                if analysis.pins:
                    pins_info = [f"引脚{p.pin_number}({p.mode})" for p in analysis.pins.values()]
                    reasoning += f"- 引脚使用: {pins_info}\n"
                if analysis.libraries:
                    reasoning += f"- 库依赖: {analysis.libraries}\n"
        
        return reasoning
    
    # ============================================================================
    # 辅助方法
    # ============================================================================
    
    def _discover_code_files(self, repo_path: Path) -> List[str]:
        """发现仓库中的代码文件"""
        code_files = []
        
        for pattern in ["*.py", "*.cpp", "*.c", "*.h", "*.hpp", "*.ino"]:
            for file_path in repo_path.rglob(pattern):
                # 跳过隐藏目录和常见非源码目录
                parts = file_path.relative_to(repo_path).parts
                if any(p.startswith('.') or p in ['node_modules', '__pycache__', 'venv', '.git'] 
                       for p in parts):
                    continue
                code_files.append(str(file_path.relative_to(repo_path)))
        
        # 限制文件数量（256K 上下文可以处理更多）
        max_files = 50
        if len(code_files) > max_files:
            self.logger.warning(f"文件数量过多 ({len(code_files)})，限制为前 {max_files} 个")
            code_files = code_files[:max_files]
        
        return code_files


# ================================================================================
# 便捷函数
# ================================================================================

def analyze_repository(
    repo_path: str,
    issue_title: str,
    issue_body: str
) -> Tuple[List[str], str]:
    """
    便捷函数：分析仓库并返回需要修改的文件
    
    Returns:
        (files_to_modify, analysis_reasoning)
    """
    analyzer = CodeAnalyzer()
    files, graph, reasoning = analyzer.analyze_for_issue(
        Path(repo_path),
        issue_title,
        issue_body
    )
    return files, reasoning


if __name__ == "__main__":
    # 简单测试
    import tempfile
    import os
    
    # 创建测试仓库
    with tempfile.TemporaryDirectory() as tmpdir:
        # 创建测试文件
        (Path(tmpdir) / "main.py").write_text("""
def read_sensor():
    return 42

def main():
    value = read_sensor()
    print(value)
""")
        
        (Path(tmpdir) / "sensor.ino").write_text("""
#include <Wire.h>

const int SENSOR_PIN = A0;

void setup() {
    Serial.begin(9600);
    pinMode(SENSOR_PIN, INPUT);
}

void loop() {
    int value = analogRead(SENSOR_PIN);
    Serial.println(value);
    delay(1000);
}
""")
        
        # 分析
        analyzer = CodeAnalyzer()
        files, graph, reasoning = analyzer.analyze_for_issue(
            Path(tmpdir),
            "Fix analogRead not working",
            "The sensor reading from A0 is always 0, need to check pin configuration"
        )
        
        print("分析结果:")
        print(f"建议修改文件: {files}")
        print("\n" + reasoning)
