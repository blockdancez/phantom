"""集中式 logging 配置：控制台 + 文件双路输出，半结构化格式。

格式：`时间 级别 [线程号] 类名 - 内容`
错误日志通过 logger.exception() 自动带错误类型和堆栈。
"""
from __future__ import annotations

import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

DEFAULT_LOG_DIR = Path("/Users/lapsdoor/phantom/logs")
LOG_FILE_NAME = "ai-design.log"

_LOG_FORMAT = "%(asctime)s.%(msecs)03d %(levelname)-5s [%(thread)d] %(name)s - %(message)s"
_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"

_configured = False


def setup_logging(level: int | str = logging.INFO) -> Path:
    """配置 root logger：控制台 + 文件 handler。幂等。返回日志文件绝对路径。"""
    global _configured
    log_dir = Path(os.environ.get("AI_DESIGN_LOG_DIR") or str(DEFAULT_LOG_DIR))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / LOG_FILE_NAME

    if _configured:
        return log_file

    formatter = logging.Formatter(_LOG_FORMAT, datefmt=_DATE_FORMAT)

    root = logging.getLogger()
    root.setLevel(level)
    for h in list(root.handlers):
        root.removeHandler(h)

    console = logging.StreamHandler(stream=sys.stdout)
    console.setFormatter(formatter)
    console.setLevel(level)
    root.addHandler(console)

    file_handler = RotatingFileHandler(
        log_file, maxBytes=50 * 1024 * 1024, backupCount=10, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(level)
    root.addHandler(file_handler)

    logging.getLogger("urllib3").setLevel(logging.WARNING)
    logging.getLogger("asyncio").setLevel(logging.WARNING)

    _configured = True
    return log_file
