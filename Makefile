.PHONY: help venv setup config install lint format test type-check clean start dev diagnose check-venv

# Python 虚拟环境目录
VENV_DIR ?= venv
PYTHON = $(VENV_DIR)/bin/python
PIP = $(VENV_DIR)/bin/pip

help:
	@echo "GitHub Agent V3 - 开发命令"
	@echo ""
	@echo "  make venv             创建 Python 虚拟环境"
	@echo "  make setup            完整环境设置（创建 venv + 安装依赖）"
	@echo "  make config           交互式配置管理（菜单导航、按需修改）"
	@echo "  make install          安装依赖（需在虚拟环境中）"
	@echo "  make lint             代码检查 (ruff)"
	@echo "  make format           代码格式化 (black)"
	@echo "  make type-check       类型检查 (mypy)"
	@echo "  make test             运行测试"
	@echo "  make test-core        运行核心模块测试"
	@echo "  make clean            清理临时文件"
	@echo "  make clean-all        清理所有（含虚拟环境）"
	@echo "  make start            启动服务（生产模式）"
	@echo "  make dev              以调试模式启动"
	@echo "  make diagnose         运行诊断检查"
	@echo ""
	@echo "快速开始:"
	@echo "  1. make setup         # 设置环境"
	@echo "  2. make config        # 配置参数（菜单式交互）"
	@echo "  3. make dev           # 启动服务"

# 检查虚拟环境是否激活（不强制，仅警告）
check-venv:
	@if [ -z "$$VIRTUAL_ENV" ]; then \
		echo "⚠️  警告: 未检测到虚拟环境，建议先运行: source $(VENV_DIR)/bin/activate"; \
		echo "   或者运行: make setup 创建并配置虚拟环境"; \
		echo ""; \
		sleep 1; \
	else \
		echo "✅ 虚拟环境已激活: $$VIRTUAL_ENV"; \
	fi

# 创建虚拟环境（如果不存在）
venv:
	@if [ -d "$(VENV_DIR)" ]; then \
		echo "✅ 虚拟环境已存在: $(VENV_DIR)"; \
		echo "   激活命令: source $(VENV_DIR)/bin/activate"; \
	else \
		echo "🔧 正在创建虚拟环境 $(VENV_DIR)..."; \
		python3 -m venv $(VENV_DIR); \
		echo "✅ 虚拟环境创建完成"; \
		echo ""; \
		echo "📋 下一步:"; \
		echo "   1. 激活环境: source $(VENV_DIR)/bin/activate"; \
		echo "   2. 安装依赖: make install"; \
		echo ""; \
		echo "   或者一键完成: make setup"; \
	fi

# 完整环境设置（创建 venv + 安装依赖）
setup: venv
	@echo "🔧 正在安装依赖..."
	$(PIP) install --upgrade pip
	$(PIP) install -r requirements.txt
	@echo ""
	@echo "✅ 环境设置完成！"
	@echo ""
	@echo "📋 使用方法:"
	@echo "   1. 配置环境: make config"
	@echo "   2. 启动服务: make dev"
	@echo ""

# 交互式配置向导（支持菜单导航、按需修改）
config: check-venv
	@python scripts/config_wizard.py

# 安装依赖（推荐在虚拟环境中运行）
install: check-venv
	pip install -r requirements.txt

# 代码检查
lint: check-venv
	ruff check core/ services/ tests/

# 代码格式化
format: check-venv
	black core/ services/ tests/
	ruff check --fix core/ services/ tests/

# 类型检查
type-check: check-venv
	mypy core/ services/ --strict --ignore-missing-imports

# 运行测试
test: check-venv
	python -m pytest tests/core/ -v --tb=short

# 运行核心模块测试（不包含集成测试）
test-core: check-venv
	python -m pytest tests/core/ -v -k "not integration"

# 清理临时文件和虚拟环境
clean:
	@echo "🧹 清理临时文件..."
	find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	find . -type f -name ".DS_Store" -delete
	rm -rf .pytest_cache .mypy_cache .coverage htmlcov
	@echo "✅ 临时文件清理完成"

clean-all: clean
	@echo "🧹 清理虚拟环境..."
	rm -rf $(VENV_DIR)
	@echo "✅ 虚拟环境已删除"

# 启动服务（生产模式）
start: check-venv
	python main.py

# 以调试模式启动
dev: check-venv
	LOG_LEVEL=DEBUG AGENT_DEBUG=true python main.py

# 运行诊断检查
diagnose: check-venv
	python diagnose.py

# 备份数据
backup: check-venv
	python -c "from core.storage import get_storage; get_storage().backup()"

# 查看磁盘使用
usage: check-venv
	python -c "from core.storage import get_storage; import json; print(json.dumps(get_storage().get_disk_usage().to_dict(), indent=2))"

# 清理临时文件
cleanup: check-venv
	python -c "from core.storage import get_storage; s = get_storage(); s.cleanup_tmp(); s.cleanup_old_logs()"

# 导出依赖（用于锁定版本）
freeze: check-venv
	pip freeze > requirements.lock.txt
	@echo "✅ 依赖已导出到 requirements.lock.txt"
