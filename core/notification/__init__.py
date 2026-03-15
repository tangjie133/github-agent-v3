"""
通知模块

提供：
- EmailNotifier: 邮件通知管理员
- 排队提示消息生成
"""

from core.notification.email import EmailNotifier, get_email_notifier

__all__ = [
    'EmailNotifier',
    'get_email_notifier',
]