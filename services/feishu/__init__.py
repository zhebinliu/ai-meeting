"""Feishu (Lark) integration module for meeting minutes and requirements output.

Modules:
    auth: OAuth 2.0 tenant access token management
    doc_writer: Create and populate Feishu documents with meeting minutes
    bitable_writer: Write requirements to Feishu Bitable
    templates: Document content templates for consistent formatting
"""

from .auth import FeishuAuth, FeishuAPIError, FeishuAuthError, FeishuRateLimitError
from .doc_writer import FeishuDocWriter
from .bitable_writer import FeishuBitableWriter
from .templates import DocTemplates

__all__ = [
    "FeishuAuth",
    "FeishuDocWriter",
    "FeishuBitableWriter",
    "DocTemplates",
    "FeishuAPIError",
    "FeishuAuthError",
    "FeishuRateLimitError",
]
