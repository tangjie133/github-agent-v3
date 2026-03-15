"""
Knowledge Base Module

Provides RAG (Retrieval-Augmented Generation) capabilities via KB Service.
"""

from .kb_client import KBClient
from .kb_integrator import KBIntegrator
from .local_kb import LocalKBManager

__all__ = [
    "KBClient",
    "KBIntegrator",
    "LocalKBManager"
]
