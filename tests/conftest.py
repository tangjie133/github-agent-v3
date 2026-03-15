"""
Pytest 配置
"""

import os
import sys

# 添加项目根目录到 Python 路径（在导入任何项目模块之前）
project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# 导入所有 fixtures
pytest_plugins = []