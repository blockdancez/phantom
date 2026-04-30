"""SDK 错误分类（spec § 5.2）。"""

from __future__ import annotations


class RetryableError(Exception):
    """临时错误，交给调度器自动重试（在 max_retries 内）。"""


class FatalError(Exception):
    """不可恢复错误，工作流进入 AWAITING_MANUAL_ACTION 等人工介入。"""
