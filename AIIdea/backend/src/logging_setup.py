"""Semi-structured logging that conforms to project rules.

Each line:

    <ISO 时间>  <LEVEL>  [<thread>]  <logger>  -  <event>  k1=v1 k2=v2 ...

- 时间：ISO 8601 UTC
- 级别：DEBUG / INFO / WARNING / ERROR / CRITICAL
- 线程号：``threading.current_thread().name``
- 类名：structlog logger name（caller 模块 / FastAPI / uvicorn 等）
- 内容：``event``（自由文本）+ 任意 key=value 字段
- request_id 通过 ``contextvars`` 自动注入到每条日志的 kv 段
- service_name 同样进 kv 段
- 错误日志带 ``error_type=<ExceptionClass>`` + 堆栈附在后续行（structlog
  自动 expand stack）
- 涉及用户操作时调用方用 ``logger.info("...", user_id=...)`` 即可

输出同时写控制台和滚动文件（默认 ``backend/var/logs/backend.log``，单文件
10 MB × 5 份；``LOG_FILE`` env 可覆盖路径，置空字符串可关闭文件输出）。

第三方库（uvicorn / apscheduler / openai / httpx ...）的日志通过同一
formatter 转译为相同行格式。
"""
from __future__ import annotations

import logging
import logging.handlers
import os
import secrets
import string
from pathlib import Path

import structlog
from structlog.processors import CallsiteParameter, CallsiteParameterAdder

SERVICE_NAME = "ai-idea-api"

_DEFAULT_LOG_FILE = Path("/Users/lapsdoor/phantom/logs/ai-idea.log")
_LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
_LOG_FILE_BACKUP_COUNT = 5

_NOISY_LOGGERS = (
    "httpx",
    "httpcore",
    "httpcore.http11",
    "httpcore.connection",
    "urllib3",
    "openai",
    "openai._base_client",
    "langchain",
    "langchain_openai",
    "langsmith",
    "asyncio",
    "apscheduler.scheduler",
    "apscheduler.executors.default",
    "trafilatura",
    "feedparser",
)


def _inject_service_name(_, __, event_dict):
    event_dict.setdefault("service_name", SERVICE_NAME)
    return event_dict


_RESERVED_KEYS = {
    "timestamp",
    "level",
    "thread_name",
    "logger",
    "event",
    "exception",
    "stack_info",
    "_record",
    "_from_structlog",
}


def _format_kv(value) -> str:
    """Render a single value, quoting when it contains whitespace or quotes."""
    s = str(value)
    if not s:
        return '""'
    if any(c in s for c in (" ", "\t", '"', "=")):
        s = s.replace("\\", "\\\\").replace('"', '\\"')
        return f'"{s}"'
    return s


def _semi_structured_renderer(_, __, event_dict):
    """Render event_dict as a single semi-structured log line.

    Format: ``<ts>  <LEVEL>  [<thread>]  <logger>  -  <event>  kv...``
    Trailing newline + indented stack (if any) preserves multi-line tracebacks.
    """
    ts = event_dict.pop("timestamp", "")
    level = str(event_dict.pop("level", "info")).upper()
    thread = event_dict.pop("thread_name", "MainThread")
    logger_name = event_dict.pop("logger", event_dict.pop("logger_name", "-"))
    event = event_dict.pop("event", "")
    exception = event_dict.pop("exception", None)
    event_dict.pop("stack_info", None)

    parts = [
        ts,
        f"{level:<5}",
        f"[{thread}]",
        str(logger_name),
        "-",
        str(event),
    ]
    head = "  ".join(p for p in parts if p)

    extras = " ".join(
        f"{k}={_format_kv(v)}" for k, v in event_dict.items() if k not in _RESERVED_KEYS
    )
    line = head if not extras else f"{head}  {extras}"
    if exception:
        line = f"{line}\n{exception}"
    return line


def setup_logging(log_level: str = "INFO") -> None:
    level = getattr(logging, log_level.upper(), logging.INFO)

    shared_processors = [
        structlog.contextvars.merge_contextvars,
        _inject_service_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        CallsiteParameterAdder(parameters={CallsiteParameter.THREAD_NAME}),
        structlog.processors.TimeStamper(fmt="iso", utc=True),
    ]

    structlog.configure(
        processors=[
            *shared_processors,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        processor=_semi_structured_renderer,
        foreign_pre_chain=shared_processors,
    )

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)

    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.addHandler(console_handler)
    root.setLevel(level)

    log_file_env = os.environ.get("LOG_FILE")
    if log_file_env is None:
        log_file: Path | None = _DEFAULT_LOG_FILE
    elif log_file_env.strip() == "":
        log_file = None
    else:
        log_file = Path(log_file_env)

    if log_file is not None:
        try:
            log_file.parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                str(log_file),
                maxBytes=_LOG_FILE_MAX_BYTES,
                backupCount=_LOG_FILE_BACKUP_COUNT,
                encoding="utf-8",
            )
            file_handler.setFormatter(formatter)
            root.addHandler(file_handler)
        except OSError as exc:
            logging.getLogger(__name__).warning(
                "日志文件初始化失败",
                extra={"path": str(log_file), "error": str(exc)},
            )

    if level > logging.DEBUG:
        for name in _NOISY_LOGGERS:
            logging.getLogger(name).setLevel(logging.WARNING)

    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).setLevel(level)


_REQUEST_ID_ALPHABET = string.ascii_letters + string.digits


def generate_request_id() -> str:
    return "".join(secrets.choice(_REQUEST_ID_ALPHABET) for _ in range(16))
