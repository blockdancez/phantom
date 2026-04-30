"""结构化日志配置与 request_id 注入。

日志规范（半结构化 / "kv" 格式，便于 grep 又能机器解析）：

    <ISO 时间戳> <LEVEL> [<thread>] <logger> <message> key1=val1 key2=val2 ...

错误日志额外带 ``error_type`` 和 ``traceback``。涉及用户操作的代码点应显式带
上 ``user_id=...`` 字段（业务层显式传入；本模块不主动注入）。

format='json' 仍保留以兼容 SaaS 日志收集器；默认 'kv'。
日志同时输出到控制台（stdout）和 ``log_file``（如配置）。
"""

from __future__ import annotations

import logging
import logging.handlers
import shlex
import sys
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from pathlib import Path
from typing import IO, Any

import structlog

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> Token[str | None]:
    """绑定 request_id 到当前 asyncio 上下文；返回 Token 供 reset 使用。"""
    return _request_id_ctx.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    """严格恢复到 bind 前的父上下文状态（嵌套 scope 安全）。"""
    _request_id_ctx.reset(token)


def clear_request_id() -> None:
    """将当前 scope 的 request_id 显式清为 None（非嵌套场景用）。"""
    _request_id_ctx.set(None)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


@contextmanager
def request_id_scope(request_id: str) -> Iterator[str]:
    token = bind_request_id(request_id)
    try:
        yield request_id
    finally:
        reset_request_id(token)


# ── structlog processors ───────────────────────────────────────────────────


def _inject_request_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    rid = _request_id_ctx.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def _inject_thread_and_logger(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """补 thread / logger 字段——半结构化格式的固定列。"""
    event_dict.setdefault("thread", threading.current_thread().name)
    name = event_dict.pop("logger", None) or getattr(logger, "name", None)
    if name:
        event_dict["logger"] = name
    return event_dict


def _rename_event_to_message(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")
    return event_dict


def _classify_exception(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    """把 ``format_exc_info`` 留下的 exception 字符串拆出 error_type，便于直接 grep。

    structlog 的 format_exc_info 跑过之后，``event_dict['exception']`` 是完整 traceback
    字符串。我们额外抽出最后一行（``ErrorType: msg``）作为 ``error_type``。
    """
    exc_text = event_dict.get("exception")
    if not exc_text or not isinstance(exc_text, str):
        return event_dict
    # 最后一行通常是 "ErrorType: message"
    last_line = exc_text.strip().splitlines()[-1] if exc_text.strip() else ""
    if ":" in last_line:
        etype = last_line.split(":", 1)[0].strip()
        if etype and " " not in etype:
            event_dict.setdefault("error_type", etype)
    event_dict["traceback"] = exc_text
    event_dict.pop("exception", None)
    return event_dict


_RESERVED_HEADER_KEYS = ("timestamp", "level", "thread", "logger", "message")


def _kv_renderer(
    logger: Any, method_name: str, event_dict: dict[str, Any]
) -> str:
    """半结构化渲染：固定列 + 余下字段以 ``k=v`` 拼接。

    格式：``<ts> <LEVEL5> [<thread>] <logger> <message> k=v ...``。
    """
    ts = event_dict.pop("timestamp", "")
    level = (event_dict.pop("level", "info") or "info").upper()
    thread = event_dict.pop("thread", "-")
    logger_name = event_dict.pop("logger", "-")
    message = event_dict.pop("message", "")
    # traceback 单独最后渲染（多行）
    traceback = event_dict.pop("traceback", None)

    # 余下字段全部 k=v；str 含空格/引号时用 shlex.quote
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


def _quote_for_kv(v: Any) -> str:
    if v is None:
        return "-"
    s = str(v)
    if not s:
        return '""'
    # 没有空格 / 引号 / 等号 → 不引；否则 shell-style 引号
    if any(c in s for c in (" ", "\t", '"', "'", "\n", "=")):
        return shlex.quote(s)
    return s


# ── configure ──────────────────────────────────────────────────────────────


def configure_logging(
    *,
    level: str = "INFO",
    format: str = "kv",
    stream: IO[str] | None = None,
    log_file: str | Path | None = None,
) -> None:
    """全局配置 structlog + stdlib logging。

    - ``format='kv'`` ：半结构化 ``<ts> <LEVEL> [<thread>] <logger> <msg> k=v...``（默认）
    - ``format='json'``：仍输出 JSON（给日志收集器）
    - ``log_file``：同时写入这个文件（10MB × 5 滚动），不传则只写 stdout
    """
    stream = stream if stream is not None else sys.stdout
    numeric_level = getattr(logging, level.upper(), None)
    if numeric_level is None:
        raise ValueError(f"Invalid log level: {level!r}")

    # 重置 stdlib root + structlog；保证多次调用幂等
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(numeric_level)

    handlers: list[logging.Handler] = [logging.StreamHandler(stream)]
    if log_file is not None:
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
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_request_id,
        _inject_thread_and_logger,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        _classify_exception,
        _rename_event_to_message,
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
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
