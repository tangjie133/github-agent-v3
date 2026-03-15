"""
工具函数

统一处理 datetime 等兼容性问题
"""

from datetime import datetime, timezone


def utc_now() -> datetime:
    """
    获取当前 UTC 时间（兼容 Python 3.10+）
    
    Python 3.12 中 datetime.utcnow() 已弃用，
    推荐使用 datetime.now(timezone.utc)
    """
    return datetime.now(timezone.utc)


def utc_now_iso() -> str:
    """获取当前 UTC 时间的 ISO 格式字符串"""
    return utc_now().isoformat().replace('+00:00', 'Z')


def format_datetime(dt: datetime) -> str:
    """格式化 datetime 为 ISO 字符串"""
    if dt.tzinfo is None:
        # 假设是 UTC 时间，添加时区信息
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat().replace('+00:00', 'Z')


def parse_datetime(iso_string: str) -> datetime:
    """解析 ISO 格式字符串为 datetime"""
    # 处理 'Z' 后缀
    if iso_string.endswith('Z'):
        iso_string = iso_string[:-1] + '+00:00'
    return datetime.fromisoformat(iso_string)