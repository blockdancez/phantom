"""SDK 侧 structlog 默认配置：半结构化输出 + 同时落盘文件，与 scheduler 对齐。

格式：``<ISO 时间戳> <LEVEL> [<thread>] <logger> <message> k=v ...``
错误日志额外带 ``error_type`` 和 ``traceback``。

可通过环境变量覆盖：
- ``AIJUICER_LOG_LEVEL``  默认 INFO
- ``AIJUICER_LOG_FORMAT`` 默认 kv（其它值：json / console）
- ``AIJUICER_LOG_FILE``   不设则只写 stdout
"""

from __future__ import annotations

import logging
import logging.handlers
import os
import shlex
import sys
import threading
from pathlib import Path
from typing import Any

import structlog

_RESERVED_HEADER_KEYS = ("timestamp", "level", "thread", "logger", "message")


def _inject_thread_and_logger(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    event_dict.setdefault("thread", threading.current_thread().name)
    name = event_dict.pop("logger", None) or getattr(logger, "name", None)
    if name:
        event_dict["logger"] = name
    return event_dict


def _classify_exception(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    exc_text = event_dict.get("exception")
    if not exc_text or not isinstance(exc_text, str):
        return event_dict
    last_line = exc_text.strip().splitlines()[-1] if exc_text.strip() else ""
    if ":" in last_line:
        etype = last_line.split(":", 1)[0].strip()
        if etype and " " not in etype:
            event_dict.setdefault("error_type", etype)
    event_dict["traceback"] = exc_text
    event_dict.pop("exception", None)
    return event_dict


def _quote_for_kv(v: Any) -> str:
    if v is None:
        return "-"
    s = str(v)
    if not s:
        return '""'
    if any(c in s for c in (" ", "\t", '"', "'", "\n", "=")):
        return shlex.quote(s)
    return s


def _kv_renderer(logger: Any, method_name: str, event_dict: dict[str, Any]) -> str:
    ts = event_dict.pop("timestamp", "")
    level = (event_dict.pop("level", "info") or "info").upper()
    thread = event_dict.pop("thread", "-")
    logger_name = event_dict.pop("logger", "-")
    message = event_dict.pop("message", "")
    traceback = event_dict.pop("traceback", None)

    parts: list[str] = [
        f"{ts}",
        f"{level:<5}",
        f"[{thread}]",
        f"{logger_name}",
        _quote_for_kv(message),
    ]
    for k in sorted(event_dict.keys()):
        if k in _RESERVED_HEADER_KEYS:
            continue
        parts.append(f"{k}={_quote_for_kv(event_dict[k])}")
    line = " ".join(parts)
    if traceback:
        line = f"{line}\n{traceback}"
    return line


def configure_sdk_logging(
    level: str | None = None,
    *,
    format: str | None = None,
    log_file: str | Path | None = None,
) -> None:
    """配置 SDK 进程内的 structlog + stdlib logging（同步 scheduler 规范）。

    参数全部可选；不传时回落到环境变量 / 默认值。
    """
    level = level or os.environ.get("AIJUICER_LOG_LEVEL", "INFO")
    format = format or os.environ.get("AIJUICER_LOG_FORMAT", "kv")
    if log_file is None:
        env_file = os.environ.get("AIJUICER_LOG_FILE")
        log_file = env_file if env_file else None
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(numeric_level)

    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if log_file:
        path = Path(log_file)
        path.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            logging.handlers.RotatingFileHandler(
                str(path), maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8"
            )
        )
    fmt = logging.Formatter("%(message)s")
    for h in handlers:
        h.setLevel(numeric_level)
        h.setFormatter(fmt)
        root.addHandler(h)

    structlog.reset_defaults()
    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_thread_and_logger,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _classify_exception,
        structlog.processors.EventRenamer("message"),
    ]
    if format == "json":
        processors.append(structlog.processors.JSONRenderer())
    elif format == "console":
        processors.append(structlog.dev.ConsoleRenderer())
    elif format == "kv":
        processors.append(_kv_renderer)
    else:
        raise ValueError(f"Invalid log format: {format!r}; expected one of kv/json/console")

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )
