"""Logging configuration.

Spec:
- Semi-structured: `time level [thread] [logger] event=<name> k=v ...`
- Errors carry exception type + stack via structlog's `format_exc_info`
- Routed to stdout AND a rotating file at `<LOG_DIR>/<SERVICE_NAME>.log`
  (defaults: `/Users/lapsdoor/phantom/logs/ai-requirement.log`; both override
  via env or `Settings`)
- Use stdlib `logging` underneath (via structlog.stdlib.LoggerFactory) — do not
  use `print` for log output anywhere in the codebase
- Per call site: include `user_id=` (and other IDs) as kwargs for user-facing
  operations; `request_id` is auto-bound by RequestIdMiddleware contextvars
"""
import logging
import logging.handlers
import sys
import uuid
from pathlib import Path

import structlog

from app.config import get_settings

LOG_FILE_MAX_BYTES = 10 * 1024 * 1024
LOG_FILE_BACKUPS = 5

LINE_FORMAT = (
    "%(asctime)s.%(msecs)03d %(levelname)-5s "
    "[%(threadName)s] [%(name)s] %(message)s"
)
DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


def setup_logging(log_level: str = "INFO") -> None:
    settings = get_settings()
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / f"{settings.service_name}.log"

    level = getattr(logging, log_level.upper(), logging.INFO)
    formatter = logging.Formatter(LINE_FORMAT, datefmt=DATE_FORMAT)

    console_handler = logging.StreamHandler(sys.stderr)
    console_handler.setFormatter(formatter)

    file_handler = logging.handlers.RotatingFileHandler(
        log_file,
        maxBytes=LOG_FILE_MAX_BYTES,
        backupCount=LOG_FILE_BACKUPS,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    root.addHandler(console_handler)
    root.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.filter_by_level,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.processors.KeyValueRenderer(
                key_order=["event"], drop_missing=True,
            ),
        ],
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        # No cache: we want loggers that 3rd-party libs (e.g. aijuicer_sdk)
        # bind early to still pick up our processors.
        cache_logger_on_first_use=False,
    )


def generate_request_id() -> str:
    return str(uuid.uuid4())
