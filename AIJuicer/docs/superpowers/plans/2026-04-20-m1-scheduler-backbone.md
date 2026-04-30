# M1: Scheduler Backbone Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 Scheduler 后端骨架——PostgreSQL schema + 6-step 状态机 + 核心 REST API + 结构化日志（全链路 request_id）。完成后，通过 HTTP API 可以创建 workflow、查询状态、模拟 agent 的 task 生命周期（start/complete/fail）、审批推进——全部状态机行为通过测试验证。

**Architecture:** Python 3.11 + FastAPI (asyncio) + SQLAlchemy 2.x async + asyncpg + Alembic migrations。structlog JSON 日志 + asyncio ContextVar 贯穿 request_id。此里程碑不含 Redis Streams 集成和 Agent SDK（M2 引入）——task 入队点留 TODO 钩子。

**Tech Stack:**
- Python 3.11, FastAPI, uvicorn, asyncpg, SQLAlchemy 2.0 async, Alembic
- structlog, pydantic-settings
- pytest, pytest-asyncio, httpx (ASGI 测试), testcontainers-postgres
- ruff, mypy, pre-commit

**Spec 引用：** `docs/superpowers/specs/2026-04-20-aiclusterschedule-design.md` § 1-4, § 6, § 9

---

## 文件结构

```
AIClusterSchedule/
├── .env.example
├── .gitignore
├── .pre-commit-config.yaml
├── Makefile
├── pyproject.toml
├── alembic.ini
├── alembic/
│   ├── env.py
│   ├── script.py.mako
│   └── versions/
│       └── 0001_initial_schema.py
└── scheduler/
    ├── __init__.py
    ├── main.py                    # FastAPI 应用入口
    ├── config.py                  # Pydantic Settings
    ├── observability/
    │   ├── __init__.py
    │   ├── logging.py             # structlog 配置
    │   └── middleware.py          # request_id middleware
    ├── storage/
    │   ├── __init__.py
    │   ├── db.py                  # async engine + session
    │   └── models.py              # SQLAlchemy ORM 模型
    ├── engine/
    │   ├── __init__.py
    │   ├── state_machine.py       # 状态转换规则
    │   ├── workflow_service.py
    │   ├── task_service.py
    │   └── approval_service.py
    ├── api/
    │   ├── __init__.py
    │   ├── workflows.py
    │   ├── tasks.py
    │   ├── approvals.py
    │   ├── agents.py
    │   └── schemas.py             # Pydantic 请求/响应模型
    └── tests/
        ├── __init__.py
        ├── conftest.py
        ├── test_state_machine.py
        ├── test_logging.py
        ├── test_workflow_service.py
        ├── test_task_service.py
        ├── test_approval_service.py
        └── test_api.py
```

---

## Task 1: 项目初始化与开发工具链

**Files:**
- Create: `pyproject.toml`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `Makefile`
- Create: `.pre-commit-config.yaml`

### Step 1.1: 创建 `pyproject.toml`

- [ ] 创建文件，内容如下：

```toml
[project]
name = "aiclusterschedule"
version = "0.1.0"
description = "AI 端到端软件交付流水线调度平台"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.110",
    "uvicorn[standard]>=0.27",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "pydantic>=2.6",
    "pydantic-settings>=2.2",
    "structlog>=24.1",
    "python-json-logger>=2.0",
    "httpx>=0.27",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-cov>=4.1",
    "testcontainers[postgres]>=4.0",
    "ruff>=0.3",
    "mypy>=1.8",
    "pre-commit>=3.6",
]

[build-system]
requires = ["setuptools>=68", "wheel"]
build-backend = "setuptools.build_meta"

[tool.setuptools.packages.find]
include = ["scheduler*"]

[tool.ruff]
line-length = 100
target-version = "py311"

[tool.ruff.lint]
select = ["E", "F", "I", "B", "UP", "T20"]  # T20 禁用 print

[tool.mypy]
python_version = "3.11"
strict = true
ignore_missing_imports = true

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["scheduler/tests"]
```

### Step 1.2: 创建 `.gitignore`

- [ ] 创建文件：

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
.env
.pytest_cache/
.mypy_cache/
.ruff_cache/
.coverage
htmlcov/
dist/
build/
*.log
.DS_Store
```

### Step 1.3: 创建 `.env.example`

- [ ] 创建文件：

```
# Scheduler
AIJUICER_DATABASE_URL=postgresql+asyncpg://aijuicer:aicluster@localhost:5432/aijuicer
AIJUICER_REDIS_URL=redis://localhost:6379/0
AIJUICER_ARTIFACT_ROOT=/var/lib/aijuicer/artifacts

AIJUICER_HEARTBEAT_TIMEOUT_SEC=90
AIJUICER_HEARTBEAT_INTERVAL_SEC=30
AIJUICER_MAX_RETRIES=3

AIJUICER_LOG_LEVEL=INFO
AIJUICER_LOG_FORMAT=json
```

### Step 1.4: 创建 `Makefile`

- [ ] 创建文件：

```makefile
.PHONY: install test lint type migrate run clean

install:
	pip install -e ".[dev]"
	pre-commit install

test:
	pytest -v --cov=scheduler --cov-report=term-missing

lint:
	ruff check scheduler
	ruff format --check scheduler

fmt:
	ruff format scheduler
	ruff check --fix scheduler

type:
	mypy scheduler

migrate:
	alembic upgrade head

run:
	uvicorn scheduler.main:app --reload --host 0.0.0.0 --port 8000

clean:
	find . -type d -name __pycache__ -exec rm -rf {} +
	rm -rf .pytest_cache .mypy_cache .ruff_cache .coverage htmlcov
```

### Step 1.5: 创建 `.pre-commit-config.yaml`

- [ ] 创建文件：

```yaml
repos:
  - repo: https://github.com/astral-sh/ruff-pre-commit
    rev: v0.3.0
    hooks:
      - id: ruff
        args: [--fix]
      - id: ruff-format
  - repo: local
    hooks:
      - id: no-print
        name: Reject print / console.log
        entry: 'print\(|console\.log'
        language: pygrep
        types_or: [python, javascript, typescript]
```

### Step 1.6: 安装依赖并验证

- [ ] 创建 venv + 安装：

```bash
cd /Users/doorlaps/workspace/claude/phantom/AIClusterSchedule
python3.11 -m venv .venv
source .venv/bin/activate
make install
```

- [ ] 验证 ruff/mypy/pytest 可用：

```bash
ruff --version
mypy --version
pytest --version
```

Expected: 所有三个命令打印版本号。

### Step 1.7: 初始化 git 仓库并首次提交

- [ ] 运行：

```bash
git init
git add .gitignore pyproject.toml .env.example Makefile .pre-commit-config.yaml
git commit -m "chore: bootstrap project toolchain (pyproject/ruff/mypy/pytest)"
```

---

## Task 2: 结构化日志基础设施（request_id 全链路）

**Files:**
- Create: `scheduler/__init__.py` (空文件)
- Create: `scheduler/observability/__init__.py` (空文件)
- Create: `scheduler/observability/logging.py`
- Create: `scheduler/observability/middleware.py`
- Create: `scheduler/tests/__init__.py` (空文件)
- Create: `scheduler/tests/test_logging.py`

### Step 2.1: 创建包 `__init__.py` 空文件

- [ ] 创建三个空文件：

```bash
mkdir -p scheduler/observability scheduler/tests
touch scheduler/__init__.py scheduler/observability/__init__.py scheduler/tests/__init__.py
```

### Step 2.2: 写 `test_logging.py` 失败测试（request_id 注入）

- [ ] 创建 `scheduler/tests/test_logging.py`：

```python
import json
import logging
from io import StringIO

import pytest
import structlog

from scheduler.observability.logging import (
    bind_request_id,
    clear_request_id,
    configure_logging,
    get_logger,
    get_request_id,
)


@pytest.fixture(autouse=True)
def _configure_structlog_for_test():
    buffer = StringIO()
    configure_logging(level="INFO", format="json", stream=buffer)
    yield buffer
    clear_request_id()


def test_request_id_injected_into_log(_configure_structlog_for_test):
    bind_request_id("req_abc123")
    get_logger("test").info("hello", foo="bar")

    log_line = _configure_structlog_for_test.getvalue().strip().splitlines()[-1]
    record = json.loads(log_line)
    assert record["request_id"] == "req_abc123"
    assert record["foo"] == "bar"
    assert record["message"] == "hello"
    assert record["level"] == "info"
    assert "timestamp" in record


def test_request_id_cleared_between_contexts(_configure_structlog_for_test):
    bind_request_id("req_first")
    get_logger("test").info("first")
    clear_request_id()
    get_logger("test").info("second")

    lines = _configure_structlog_for_test.getvalue().strip().splitlines()
    first = json.loads(lines[-2])
    second = json.loads(lines[-1])
    assert first["request_id"] == "req_first"
    assert "request_id" not in second or second["request_id"] is None


def test_get_request_id_returns_bound_value(_configure_structlog_for_test):
    bind_request_id("req_xyz")
    assert get_request_id() == "req_xyz"
```

### Step 2.3: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_logging.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'scheduler.observability.logging'`

### Step 2.4: 实现 `scheduler/observability/logging.py`

- [ ] 创建文件：

```python
"""结构化日志配置与 request_id 注入。"""
from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import IO, Any

import structlog

_request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)


def bind_request_id(request_id: str) -> None:
    """绑定 request_id 到当前 asyncio 上下文。"""
    _request_id_ctx.set(request_id)


def clear_request_id() -> None:
    _request_id_ctx.set(None)


def get_request_id() -> str | None:
    return _request_id_ctx.get()


def _inject_request_id(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    rid = _request_id_ctx.get()
    if rid is not None:
        event_dict["request_id"] = rid
    return event_dict


def _rename_event_to_message(
    logger: logging.Logger, method_name: str, event_dict: dict[str, Any]
) -> dict[str, Any]:
    if "event" in event_dict:
        event_dict["message"] = event_dict.pop("event")
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    format: str = "json",
    stream: IO[str] | None = None,
) -> None:
    """全局配置 structlog + stdlib logging。

    format='json' 输出 JSON；format='console' 输出人类可读（开发用）。
    """
    stream = stream if stream is not None else sys.stdout
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    logging.basicConfig(stream=stream, level=numeric_level, format="%(message)s", force=True)

    processors: list[Any] = [
        structlog.stdlib.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        _inject_request_id,
        _rename_event_to_message,
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
    ]
    if format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer())

    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(file=stream),
        cache_logger_on_first_use=True,
    )


def get_logger(name: str | None = None) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
```

### Step 2.5: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_logging.py -v
```

Expected: 3 tests PASS

### Step 2.6: 写 middleware 测试（request_id 从 header 沿用或生成）

- [ ] 追加到 `scheduler/tests/test_logging.py`：

```python
import asyncio

from fastapi import FastAPI
from fastapi.testclient import TestClient

from scheduler.observability.middleware import RequestIdMiddleware


def _build_app():
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def echo():
        return {"request_id": get_request_id()}

    return app


def test_middleware_generates_request_id_when_absent():
    app = _build_app()
    client = TestClient(app)
    resp = client.get("/echo")
    assert resp.status_code == 200
    rid = resp.json()["request_id"]
    assert rid and rid.startswith("req_")
    assert resp.headers["X-Request-ID"] == rid


def test_middleware_preserves_incoming_request_id():
    app = _build_app()
    client = TestClient(app)
    resp = client.get("/echo", headers={"X-Request-ID": "req_supplied"})
    assert resp.json()["request_id"] == "req_supplied"
    assert resp.headers["X-Request-ID"] == "req_supplied"
```

### Step 2.7: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_logging.py -v
```

Expected: 最后 2 条 FAIL with `ModuleNotFoundError: No module named 'scheduler.observability.middleware'`

### Step 2.8: 实现 `scheduler/observability/middleware.py`

- [ ] 创建文件：

```python
"""HTTP middleware: X-Request-ID 沿用或生成，并绑定到 contextvar。"""
from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from scheduler.observability.logging import bind_request_id, clear_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-ID"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(self.HEADER)
        if not rid:
            rid = "req_" + secrets.token_hex(4)
        bind_request_id(rid)
        try:
            response: Response = await call_next(request)
        finally:
            pass  # 保留直到响应发送
        response.headers[self.HEADER] = rid
        clear_request_id()
        return response


def generate_request_id() -> str:
    return "req_" + secrets.token_hex(4)
```

### Step 2.9: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_logging.py -v
```

Expected: 5 tests PASS

### Step 2.10: 提交

- [ ] 运行：

```bash
git add scheduler/__init__.py scheduler/observability scheduler/tests/__init__.py scheduler/tests/test_logging.py
git commit -m "feat(observability): structured logging with request_id contextvar + HTTP middleware"
```

---

## Task 3: 配置模块（Pydantic Settings）

**Files:**
- Create: `scheduler/config.py`
- Create: `scheduler/tests/test_config.py`

### Step 3.1: 写失败测试

- [ ] 创建 `scheduler/tests/test_config.py`：

```python
import os
from pathlib import Path

import pytest

from scheduler.config import Settings


def test_default_settings(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AIJUICER_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/test",
    )
    monkeypatch.setenv("AIJUICER_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AIJUICER_ARTIFACT_ROOT", str(tmp_path))

    s = Settings()
    assert s.database_url.startswith("postgresql+asyncpg://")
    assert s.redis_url == "redis://localhost:6379/0"
    assert s.artifact_root == tmp_path
    assert s.heartbeat_timeout_sec == 90
    assert s.heartbeat_interval_sec == 30
    assert s.max_retries == 3
    assert s.retry_backoff_sec == [60, 300, 900]
    assert set(s.step_max_duration.keys()) == {
        "finder", "requirement", "plan", "design", "devtest", "deploy"
    }
    assert s.log_format == "json"


def test_env_override(monkeypatch, tmp_path):
    monkeypatch.setenv(
        "AIJUICER_DATABASE_URL",
        "postgresql+asyncpg://u:p@localhost/test",
    )
    monkeypatch.setenv("AIJUICER_REDIS_URL", "redis://localhost:6379/0")
    monkeypatch.setenv("AIJUICER_ARTIFACT_ROOT", str(tmp_path))
    monkeypatch.setenv("AIJUICER_HEARTBEAT_TIMEOUT_SEC", "120")
    monkeypatch.setenv("AIJUICER_MAX_RETRIES", "5")

    s = Settings()
    assert s.heartbeat_timeout_sec == 120
    assert s.max_retries == 5
```

### Step 3.2: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_config.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 3.3: 实现 `scheduler/config.py`

- [ ] 创建文件：

```python
"""集中配置：从环境变量加载，Pydantic 校验。"""
from __future__ import annotations

from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="AIJUICER_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    database_url: str
    redis_url: str
    artifact_root: Path

    heartbeat_timeout_sec: int = 90
    heartbeat_interval_sec: int = 30
    max_retries: int = 3
    retry_backoff_sec: list[int] = Field(default_factory=lambda: [60, 300, 900])

    step_max_duration: dict[str, int] = Field(
        default_factory=lambda: {
            "finder": 600,
            "requirement": 1800,
            "plan": 1800,
            "design": 3600,
            "devtest": 21600,
            "deploy": 1800,
        }
    )

    log_level: str = "INFO"
    log_format: str = "json"


def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]
```

### Step 3.4: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_config.py -v
```

Expected: 2 tests PASS

### Step 3.5: 提交

- [ ] 运行：

```bash
git add scheduler/config.py scheduler/tests/test_config.py
git commit -m "feat(config): Pydantic Settings with env overrides"
```

---

## Task 4: 数据库模型与 Alembic migrations

**Files:**
- Create: `alembic.ini`
- Create: `alembic/env.py`
- Create: `alembic/script.py.mako`
- Create: `alembic/versions/0001_initial_schema.py`
- Create: `scheduler/storage/__init__.py`
- Create: `scheduler/storage/models.py`
- Create: `scheduler/storage/db.py`
- Create: `scheduler/tests/conftest.py`

### Step 4.1: 创建 SQLAlchemy 模型（6 张表）

- [ ] 创建 `scheduler/storage/__init__.py`（空文件）

- [ ] 创建 `scheduler/storage/models.py`：

```python
"""SQLAlchemy ORM 模型，映射 spec § 3.2 的 6 张表。"""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class Workflow(Base):
    __tablename__ = "workflows"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    input: Mapped[dict] = mapped_column(JSONB, nullable=False)
    approval_policy: Mapped[dict] = mapped_column(JSONB, nullable=False)
    current_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    failed_step: Mapped[str | None] = mapped_column(Text, nullable=True)
    artifact_root: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_workflows_status", "status"),)


class StepExecution(Base):
    __tablename__ = "step_executions"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    step: Mapped[str] = mapped_column(Text, nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    agent_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    input: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    output: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_heartbeat_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    heartbeat_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    request_id: Mapped[str] = mapped_column(Text, nullable=False)

    __table_args__ = (
        UniqueConstraint("workflow_id", "step", "attempt", name="uq_step_attempts"),
        Index("idx_step_executions_wf", "workflow_id"),
        Index("idx_step_executions_status", "status", "last_heartbeat_at"),
    )


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    step: Mapped[str] = mapped_column(Text, nullable=False)
    key: Mapped[str] = mapped_column(Text, nullable=False)
    path: Mapped[str] = mapped_column(Text, nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    content_type: Mapped[str | None] = mapped_column(Text, nullable=True)
    sha256: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (UniqueConstraint("workflow_id", "step", "key", name="uq_artifact_key"),)


class Approval(Base):
    __tablename__ = "approvals"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    step: Mapped[str] = mapped_column(Text, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    payload: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Agent(Base):
    __tablename__ = "agents"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    step: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metadata_: Mapped[dict | None] = mapped_column("metadata", JSONB, nullable=True)


class WorkflowEvent(Base):
    __tablename__ = "workflow_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    workflow_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("workflows.id", ondelete="CASCADE"),
        nullable=False,
    )
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict] = mapped_column(JSONB, nullable=False)
    request_id: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (Index("idx_events_wf", "workflow_id", "id"),)
```

### Step 4.2: 创建 db 引擎和 session

- [ ] 创建 `scheduler/storage/db.py`：

```python
"""异步 DB 引擎 + session factory。"""
from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scheduler.config import Settings


class Database:
    def __init__(self, settings: Settings) -> None:
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=5,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        session = self._session_factory()
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()

    async def dispose(self) -> None:
        await self._engine.dispose()
```

### Step 4.3: 初始化 Alembic

- [ ] 运行：

```bash
alembic init alembic
```

- [ ] 用以下内容覆盖 `alembic.ini`（仅关键段，保留原文件其他段）：

```ini
[alembic]
script_location = alembic
prepend_sys_path = .
version_path_separator = os
sqlalchemy.url =
```

- [ ] 用以下内容覆盖 `alembic/env.py`：

```python
"""Alembic env: 从 scheduler.config 读 URL + 同步 Postgres URL 执行迁移。"""
from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.ext.asyncio import create_async_engine

from scheduler.config import get_settings
from scheduler.storage.models import Base

config = context.config
if config.config_file_name:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_url() -> str:
    return get_settings().database_url


async def run_migrations_online() -> None:
    url = get_url()
    connectable = create_async_engine(url, poolclass=pool.NullPool)

    async with connectable.connect() as connection:
        await connection.run_sync(_do_run_migrations)

    await connectable.dispose()


def _do_run_migrations(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_offline() -> None:
    context.configure(
        url=get_url(),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
```

### Step 4.4: 生成 initial migration

- [ ] 确保本地 Postgres 启动（或用 Docker）：

```bash
docker run -d --name aijuicer-pg-dev \
  -e POSTGRES_USER=aijuicer -e POSTGRES_PASSWORD=aijuicer -e POSTGRES_DB=aijuicer \
  -p 5432:5432 postgres:15
```

- [ ] 复制 `.env.example` 到 `.env`：

```bash
cp .env.example .env
```

- [ ] 生成迁移（自动推导 schema）：

```bash
alembic revision --autogenerate -m "initial schema" -r 0001
```

- [ ] 验证生成的文件在 `alembic/versions/0001_*.py`，手动检查里面包含 6 张表的 create_table 语句。如果自动推导有差异，手工修正为与 `scheduler/storage/models.py` 一致。

### Step 4.5: 执行迁移

- [ ] 运行：

```bash
alembic upgrade head
```

Expected: 输出 `Running upgrade -> 0001, initial schema`。

- [ ] 验证 schema：

```bash
docker exec aijuicer-pg-dev psql -U aijuicer -d aijuicer -c "\dt"
```

Expected: 列出 6 张表（workflows, step_executions, artifacts, approvals, agents, workflow_events）+ alembic_version。

### Step 4.6: 创建 pytest fixture（testcontainers Postgres）

- [ ] 创建 `scheduler/tests/conftest.py`：

```python
"""Pytest fixtures: testcontainers Postgres + 测试用 Database。"""
from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession
from testcontainers.postgres import PostgresContainer

from scheduler.config import Settings
from scheduler.storage.db import Database
from scheduler.storage.models import Base


@pytest.fixture(scope="session")
def postgres_container() -> Iterator[PostgresContainer]:
    container = PostgresContainer("postgres:15")
    container.start()
    try:
        yield container
    finally:
        container.stop()


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
def test_settings(postgres_container: PostgresContainer, tmp_path_factory) -> Settings:
    raw_url = postgres_container.get_connection_url()
    async_url = raw_url.replace("postgresql+psycopg2://", "postgresql+asyncpg://").replace(
        "postgresql://", "postgresql+asyncpg://"
    )
    artifact_root = tmp_path_factory.mktemp("artifacts")
    return Settings(
        database_url=async_url,
        redis_url="redis://localhost:6379/0",
        artifact_root=artifact_root,
    )


@pytest_asyncio.fixture(scope="session")
async def database(test_settings: Settings) -> AsyncIterator[Database]:
    db = Database(test_settings)
    async with db.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield db
    await db.dispose()


@pytest_asyncio.fixture
async def db_session(database: Database) -> AsyncIterator[AsyncSession]:
    """每测试一个空 session + 回滚以保证隔离。"""
    async with database.engine.begin() as conn:
        async with AsyncSession(bind=conn, expire_on_commit=False) as session:
            yield session
            await session.rollback()
```

### Step 4.7: 运行 sanity 测试（无新测试，仅确认 import 无错）

- [ ] 运行：

```bash
pytest scheduler/tests/ -v --collect-only
```

Expected: 所有已有测试正常 collect，无 import error。

### Step 4.8: 提交

- [ ] 运行：

```bash
git add scheduler/storage scheduler/tests/conftest.py alembic.ini alembic/
git commit -m "feat(storage): SQLAlchemy models (6 tables) + alembic initial migration + async DB session"
```

---

## Task 5: State Machine 模块（核心业务规则）

**Files:**
- Create: `scheduler/engine/__init__.py`
- Create: `scheduler/engine/state_machine.py`
- Create: `scheduler/tests/test_state_machine.py`

### Step 5.1: 创建包文件

- [ ] 创建 `scheduler/engine/__init__.py`（空文件）

### Step 5.2: 写 state machine 测试（覆盖所有路径）

- [ ] 创建 `scheduler/tests/test_state_machine.py`：

```python
import pytest

from scheduler.engine.state_machine import (
    STEPS,
    InvalidTransition,
    State,
    next_running_state,
    next_state_on_failure,
    next_state_on_success,
    starting_state,
    transition,
    validate_transition,
)


def test_steps_order_matches_spec():
    assert STEPS == ("finder", "requirement", "plan", "design", "devtest", "deploy")


def test_starting_state_is_created():
    assert starting_state() == State.CREATED


def test_created_to_first_running():
    assert next_running_state(State.CREATED, policy={}) == State.FINDER_RUNNING


def test_step_done_auto_goes_to_next_running():
    policy = {"requirement": "auto"}
    nxt = next_running_state(State.FINDER_DONE, policy=policy)
    assert nxt == State.REQUIREMENT_RUNNING


def test_step_done_manual_goes_to_awaiting_approval():
    policy = {"requirement": "manual"}
    nxt = next_running_state(State.FINDER_DONE, policy=policy)
    assert nxt == State.AWAITING_APPROVAL_REQUIREMENT


def test_awaiting_approval_to_next_running():
    nxt = next_running_state(State.AWAITING_APPROVAL_REQUIREMENT, policy={})
    assert nxt == State.REQUIREMENT_RUNNING


def test_last_step_done_goes_to_completed():
    nxt = next_running_state(State.DEPLOY_DONE, policy={})
    assert nxt == State.COMPLETED


def test_success_transition():
    assert next_state_on_success(State.FINDER_RUNNING) == State.FINDER_DONE
    assert next_state_on_success(State.DEPLOY_RUNNING) == State.DEPLOY_DONE


def test_failure_transition():
    assert next_state_on_failure(State.FINDER_RUNNING) == State.AWAITING_MANUAL_ACTION
    assert next_state_on_failure(State.DEVTEST_RUNNING) == State.AWAITING_MANUAL_ACTION


def test_transition_function_accepts_valid():
    # CREATED -> FINDER_RUNNING (submit)
    transition(State.CREATED, State.FINDER_RUNNING)


def test_transition_function_rejects_invalid():
    with pytest.raises(InvalidTransition):
        transition(State.FINDER_RUNNING, State.DEPLOY_RUNNING)


def test_completed_is_terminal():
    with pytest.raises(InvalidTransition):
        transition(State.COMPLETED, State.FINDER_RUNNING)


def test_aborted_is_terminal():
    with pytest.raises(InvalidTransition):
        transition(State.ABORTED, State.FINDER_RUNNING)


def test_abort_allowed_from_any_non_terminal():
    for s in [
        State.FINDER_RUNNING,
        State.FINDER_DONE,
        State.AWAITING_APPROVAL_REQUIREMENT,
        State.REQUIREMENT_RUNNING,
        State.AWAITING_MANUAL_ACTION,
    ]:
        validate_transition(s, State.ABORTED)


def test_manual_action_recovery_paths():
    """从 AWAITING_MANUAL_ACTION 可以 resume（重跑当前步）或 skip（进下一步）或 abort。"""
    # resume: rerun current failed step -> back to RUNNING
    validate_transition(State.AWAITING_MANUAL_ACTION, State.FINDER_RUNNING)
    validate_transition(State.AWAITING_MANUAL_ACTION, State.DEVTEST_RUNNING)
    validate_transition(State.AWAITING_MANUAL_ACTION, State.ABORTED)


@pytest.mark.parametrize("step", STEPS)
def test_every_step_has_running_done_states(step):
    running = State[f"{step.upper()}_RUNNING"]
    done = State[f"{step.upper()}_DONE"]
    assert running.value.endswith("_RUNNING")
    assert done.value.endswith("_DONE")
    assert next_state_on_success(running) == done
```

### Step 5.3: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_state_machine.py -v
```

Expected: FAIL with `ModuleNotFoundError: scheduler.engine.state_machine`

### Step 5.4: 实现 state machine

- [ ] 创建 `scheduler/engine/state_machine.py`：

```python
"""6-step 固定流水线状态机（spec § 3.1）。

约束（spec § 3.1 不变量）：
- 每个 workflow 任意时刻 ≤ 1 个 running step
- 状态转换必须通过本模块的 transition/validate_transition
"""
from __future__ import annotations

from enum import Enum
from typing import Mapping

STEPS: tuple[str, ...] = ("finder", "requirement", "plan", "design", "devtest", "deploy")


class State(str, Enum):
    CREATED = "CREATED"

    FINDER_RUNNING = "FINDER_RUNNING"
    FINDER_DONE = "FINDER_DONE"
    AWAITING_APPROVAL_REQUIREMENT = "AWAITING_APPROVAL_REQUIREMENT"

    REQUIREMENT_RUNNING = "REQUIREMENT_RUNNING"
    REQUIREMENT_DONE = "REQUIREMENT_DONE"
    AWAITING_APPROVAL_PLAN = "AWAITING_APPROVAL_PLAN"

    PLAN_RUNNING = "PLAN_RUNNING"
    PLAN_DONE = "PLAN_DONE"
    AWAITING_APPROVAL_DESIGN = "AWAITING_APPROVAL_DESIGN"

    DESIGN_RUNNING = "DESIGN_RUNNING"
    DESIGN_DONE = "DESIGN_DONE"
    AWAITING_APPROVAL_DEVTEST = "AWAITING_APPROVAL_DEVTEST"

    DEVTEST_RUNNING = "DEVTEST_RUNNING"
    DEVTEST_DONE = "DEVTEST_DONE"
    AWAITING_APPROVAL_DEPLOY = "AWAITING_APPROVAL_DEPLOY"

    DEPLOY_RUNNING = "DEPLOY_RUNNING"
    DEPLOY_DONE = "DEPLOY_DONE"

    COMPLETED = "COMPLETED"
    ABORTED = "ABORTED"
    AWAITING_MANUAL_ACTION = "AWAITING_MANUAL_ACTION"


TERMINAL: frozenset[State] = frozenset({State.COMPLETED, State.ABORTED})


class InvalidTransition(Exception):
    def __init__(self, src: State, dst: State) -> None:
        super().__init__(f"Invalid state transition: {src.value} -> {dst.value}")
        self.src = src
        self.dst = dst


def starting_state() -> State:
    return State.CREATED


def _running_for(step: str) -> State:
    return State[f"{step.upper()}_RUNNING"]


def _done_for(step: str) -> State:
    return State[f"{step.upper()}_DONE"]


def _awaiting_approval_for(step: str) -> State:
    return State[f"AWAITING_APPROVAL_{step.upper()}"]


def next_state_on_success(src: State) -> State:
    """RUNNING → DONE。"""
    if not src.value.endswith("_RUNNING") or src == State.COMPLETED:
        raise InvalidTransition(src, src)
    step = src.value.removesuffix("_RUNNING").lower()
    return _done_for(step)


def next_state_on_failure(src: State) -> State:
    """RUNNING → AWAITING_MANUAL_ACTION（业务层根据重试次数决定实际调用此函数或 retry）。"""
    if not src.value.endswith("_RUNNING"):
        raise InvalidTransition(src, State.AWAITING_MANUAL_ACTION)
    return State.AWAITING_MANUAL_ACTION


def next_running_state(src: State, policy: Mapping[str, str]) -> State:
    """计算 "推进到下一步" 的目标状态。

    - CREATED → FINDER_RUNNING
    - <STEP>_DONE：
        - 若是最后一步 (deploy) → COMPLETED
        - 否则 policy[next]=auto → <NEXT>_RUNNING
        - 否则 → AWAITING_APPROVAL_<NEXT>
    - AWAITING_APPROVAL_<STEP> → <STEP>_RUNNING
    """
    if src == State.CREATED:
        return State.FINDER_RUNNING

    if src.value.endswith("_DONE"):
        step = src.value.removesuffix("_DONE").lower()
        idx = STEPS.index(step)
        if idx == len(STEPS) - 1:
            return State.COMPLETED
        next_step = STEPS[idx + 1]
        if policy.get(next_step, "manual") == "auto":
            return _running_for(next_step)
        return _awaiting_approval_for(next_step)

    if src.value.startswith("AWAITING_APPROVAL_"):
        step = src.value.removeprefix("AWAITING_APPROVAL_").lower()
        return _running_for(step)

    raise InvalidTransition(src, src)


def _build_allowed_transitions() -> set[tuple[State, State]]:
    allowed: set[tuple[State, State]] = set()

    # CREATED -> FINDER_RUNNING (submit)
    allowed.add((State.CREATED, State.FINDER_RUNNING))

    for i, step in enumerate(STEPS):
        running = _running_for(step)
        done = _done_for(step)
        # RUNNING -> DONE
        allowed.add((running, done))
        # RUNNING -> RUNNING (重试：attempt+1 进入新的 RUNNING)
        allowed.add((running, running))
        # RUNNING -> AWAITING_MANUAL_ACTION
        allowed.add((running, State.AWAITING_MANUAL_ACTION))

        if i < len(STEPS) - 1:
            next_step = STEPS[i + 1]
            next_running = _running_for(next_step)
            awaiting = _awaiting_approval_for(next_step)
            # DONE -> 下一步 RUNNING 或 AWAITING_APPROVAL
            allowed.add((done, next_running))
            allowed.add((done, awaiting))
            # AWAITING_APPROVAL -> RUNNING
            allowed.add((awaiting, next_running))
            # AWAITING_APPROVAL -> ABORTED (reject)
            allowed.add((awaiting, State.ABORTED))
        else:
            # 最后一步 DONE -> COMPLETED
            allowed.add((done, State.COMPLETED))

    # AWAITING_MANUAL_ACTION 的恢复路径：到任何 RUNNING 或 ABORTED
    for step in STEPS:
        allowed.add((State.AWAITING_MANUAL_ACTION, _running_for(step)))
    allowed.add((State.AWAITING_MANUAL_ACTION, State.ABORTED))
    # skip: AWAITING_MANUAL_ACTION -> 下一步 AWAITING_APPROVAL 或 COMPLETED
    # （人工跳过 failed step，继续下一步）
    for i, step in enumerate(STEPS):
        if i < len(STEPS) - 1:
            next_step = STEPS[i + 1]
            allowed.add((State.AWAITING_MANUAL_ACTION, _running_for(next_step)))
            allowed.add((State.AWAITING_MANUAL_ACTION, _awaiting_approval_for(next_step)))
        else:
            allowed.add((State.AWAITING_MANUAL_ACTION, State.COMPLETED))

    # 任何非终态 -> ABORTED
    for s in State:
        if s not in TERMINAL:
            allowed.add((s, State.ABORTED))

    return allowed


_ALLOWED: set[tuple[State, State]] = _build_allowed_transitions()


def validate_transition(src: State, dst: State) -> None:
    if src in TERMINAL:
        raise InvalidTransition(src, dst)
    if (src, dst) not in _ALLOWED:
        raise InvalidTransition(src, dst)


def transition(src: State, dst: State) -> State:
    """校验并返回目标状态。调用者负责在 DB 事务里持久化。"""
    validate_transition(src, dst)
    return dst
```

### Step 5.5: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_state_machine.py -v
```

Expected: 14 tests PASS (含 parametrize 展开后的 6 个)

### Step 5.6: 提交

- [ ] 运行：

```bash
git add scheduler/engine/__init__.py scheduler/engine/state_machine.py scheduler/tests/test_state_machine.py
git commit -m "feat(engine): state machine for 6-step pipeline with failure/recovery paths"
```

---

## Task 6: Workflow Service（创建 / 查询 / 驱动）

**Files:**
- Create: `scheduler/engine/workflow_service.py`
- Create: `scheduler/tests/test_workflow_service.py`

### Step 6.1: 写失败测试

- [ ] 创建 `scheduler/tests/test_workflow_service.py`：

```python
import uuid

import pytest
from sqlalchemy import select

from scheduler.engine.state_machine import State
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent


@pytest.mark.asyncio
async def test_create_workflow_initializes_state_and_enqueues_first_step(db_session):
    service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await service.create(
        name="test-wf",
        input={"topic": "video"},
        approval_policy={"requirement": "auto"},
        request_id="req_test1",
    )

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.name == "test-wf"
    assert wf.status == State.FINDER_RUNNING.value
    assert wf.current_step == "finder"
    assert wf.artifact_root.endswith(str(wf_id))

    step = (
        await db_session.execute(select(StepExecution).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()
    assert step.step == "finder"
    assert step.attempt == 1
    assert step.status == "pending"
    assert step.request_id == "req_test1"

    events = (
        await db_session.execute(
            select(WorkflowEvent)
            .where(WorkflowEvent.workflow_id == wf_id)
            .order_by(WorkflowEvent.id)
        )
    ).scalars().all()
    assert [e.event_type for e in events] == ["workflow.created", "state.changed", "task.enqueued"]


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown(db_session):
    service = WorkflowService(db_session, artifact_root="/tmp/art")
    result = await service.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_filters_by_status(db_session):
    service = WorkflowService(db_session, artifact_root="/tmp/art")
    id1 = await service.create(name="a", input={}, approval_policy={}, request_id="r1")
    id2 = await service.create(name="b", input={}, approval_policy={}, request_id="r2")

    all_wf = await service.list()
    assert len(all_wf) >= 2

    running = await service.list(status=State.FINDER_RUNNING.value)
    ids = [w.id for w in running]
    assert id1 in ids and id2 in ids
```

### Step 6.2: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_workflow_service.py -v
```

Expected: FAIL with `ModuleNotFoundError: scheduler.engine.workflow_service`

### Step 6.3: 实现 WorkflowService

- [ ] 创建 `scheduler/engine/workflow_service.py`：

```python
"""Workflow service: 创建/查询/驱动工作流状态转换。"""
from __future__ import annotations

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.engine.state_machine import STEPS, State, next_running_state, transition
from scheduler.observability.logging import get_logger
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent

logger = get_logger(__name__)


class WorkflowService:
    """所有状态转换在同一 AsyncSession 的事务内完成；调用者负责 commit。"""

    def __init__(self, session: AsyncSession, artifact_root: str | Path) -> None:
        self.session = session
        self.artifact_root = Path(artifact_root)

    async def create(
        self,
        *,
        name: str,
        input: dict,
        approval_policy: dict,
        request_id: str,
    ) -> uuid.UUID:
        """创建 workflow，持久化 CREATED → FINDER_RUNNING 的首次转换。"""
        wf_id = uuid.uuid4()
        wf_artifact_root = str(self.artifact_root / "workflows" / str(wf_id))

        wf = Workflow(
            id=wf_id,
            name=name,
            status=State.CREATED.value,
            input=input,
            approval_policy=approval_policy,
            current_step=None,
            artifact_root=wf_artifact_root,
        )
        self.session.add(wf)
        self.session.add(
            WorkflowEvent(
                workflow_id=wf_id,
                event_type="workflow.created",
                payload={"name": name},
                request_id=request_id,
            )
        )
        await self.session.flush()

        # 驱动到 FINDER_RUNNING
        await self._advance_to_running(
            wf, target=State.FINDER_RUNNING, request_id=request_id
        )
        return wf_id

    async def get(self, wf_id: uuid.UUID) -> Workflow | None:
        result = await self.session.execute(select(Workflow).where(Workflow.id == wf_id))
        return result.scalar_one_or_none()

    async def list(self, *, status: str | None = None, limit: int = 100) -> list[Workflow]:
        stmt = select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Workflow.status == status)
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def advance_on_step_success(
        self, wf_id: uuid.UUID, *, request_id: str
    ) -> State:
        """Step completed 时被 TaskService 调用：根据 approval_policy 推进。"""
        wf = await self.get(wf_id)
        if wf is None:
            raise ValueError(f"Workflow {wf_id} not found")
        src = State(wf.status)
        # 先把 RUNNING -> DONE（如果尚未做）
        if src.value.endswith("_RUNNING"):
            done = State[src.value.replace("_RUNNING", "_DONE")]
            transition(src, done)
            wf.status = done.value
            self.session.add(
                WorkflowEvent(
                    workflow_id=wf.id,
                    event_type="state.changed",
                    payload={"from": src.value, "to": done.value},
                    request_id=request_id,
                )
            )
            src = done

        target = next_running_state(src, policy=wf.approval_policy)
        transition(src, target)
        wf.status = target.value
        if target.value.endswith("_RUNNING"):
            wf.current_step = target.value.removesuffix("_RUNNING").lower()
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": target.value},
                request_id=request_id,
            )
        )

        if target.value.endswith("_RUNNING"):
            await self._enqueue_pending_step(
                wf, step=target.value.removesuffix("_RUNNING").lower(), request_id=request_id
            )
        return target

    async def _advance_to_running(
        self, wf: Workflow, *, target: State, request_id: str
    ) -> None:
        src = State(wf.status)
        transition(src, target)
        wf.status = target.value
        wf.current_step = target.value.removesuffix("_RUNNING").lower()
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": target.value},
                request_id=request_id,
            )
        )
        await self._enqueue_pending_step(
            wf, step=target.value.removesuffix("_RUNNING").lower(), request_id=request_id
        )

    async def _enqueue_pending_step(
        self, wf: Workflow, *, step: str, request_id: str
    ) -> StepExecution:
        """插入 pending step_execution。M1 暂不做 Redis XADD（M2 接入）。"""
        # 计算此 step 的下一 attempt
        result = await self.session.execute(
            select(StepExecution)
            .where(StepExecution.workflow_id == wf.id)
            .where(StepExecution.step == step)
        )
        existing = list(result.scalars().all())
        attempt = max((e.attempt for e in existing), default=0) + 1

        exec_ = StepExecution(
            workflow_id=wf.id,
            step=step,
            attempt=attempt,
            status="pending",
            input=wf.input,
            request_id=request_id,
        )
        self.session.add(exec_)
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="task.enqueued",
                payload={"step": step, "attempt": attempt, "task_id": str(exec_.id)},
                request_id=request_id,
            )
        )
        await self.session.flush()
        logger.info(
            "task.enqueued.db",
            workflow_id=str(wf.id),
            step=step,
            attempt=attempt,
            task_id=str(exec_.id),
        )
        # TODO(M2): 在 session.commit() 之后 XADD 到 Redis Streams
        return exec_
```

### Step 6.4: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_workflow_service.py -v
```

Expected: 3 tests PASS

### Step 6.5: 提交

- [ ] 运行：

```bash
git add scheduler/engine/workflow_service.py scheduler/tests/test_workflow_service.py
git commit -m "feat(engine): WorkflowService for create/list/advance (M2 Redis hook left as TODO)"
```

---

## Task 7: Task Service（task 生命周期：start / complete / fail）

**Files:**
- Create: `scheduler/engine/task_service.py`
- Create: `scheduler/tests/test_task_service.py`

### Step 7.1: 写失败测试

- [ ] 创建 `scheduler/tests/test_task_service.py`：

```python
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from scheduler.engine.state_machine import State
from scheduler.engine.task_service import TaskService
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent


@pytest.mark.asyncio
async def test_start_task_sets_running(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(
            select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
        )
    ).scalar_one()

    task_service = TaskService(db_session)
    await task_service.start(task_id=task_id, agent_id="agent-01", request_id="req_2")

    step = (
        await db_session.execute(
            select(StepExecution).where(StepExecution.id == task_id)
        )
    ).scalar_one()
    assert step.status == "running"
    assert step.agent_id == "agent-01"
    assert step.started_at is not None
    assert step.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_complete_task_marks_succeeded_and_advances_workflow(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t",
        input={},
        approval_policy={"requirement": "auto"},
        request_id="req_1",
    )
    task_id = (
        await db_session.execute(
            select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
        )
    ).scalar_one()

    task_service = TaskService(db_session)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    await task_service.complete(
        task_id=task_id, output={"idea_summary": "..."}, request_id="r3"
    )

    step = (
        await db_session.execute(
            select(StepExecution).where(StepExecution.id == task_id)
        )
    ).scalar_one()
    assert step.status == "succeeded"
    assert step.output == {"idea_summary": "..."}

    wf = (
        await db_session.execute(select(Workflow).where(Workflow.id == wf_id))
    ).scalar_one()
    assert wf.status == State.REQUIREMENT_RUNNING.value


@pytest.mark.asyncio
async def test_fail_task_retryable_creates_new_attempt(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(
            select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
        )
    ).scalar_one()

    task_service = TaskService(db_session, max_retries=3)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    new_task_id = await task_service.fail(
        task_id=task_id, error="boom", retryable=True, request_id="r3"
    )

    assert new_task_id is not None and new_task_id != task_id

    step1 = (await db_session.execute(
        select(StepExecution).where(StepExecution.id == task_id)
    )).scalar_one()
    assert step1.status == "failed"

    step2 = (await db_session.execute(
        select(StepExecution).where(StepExecution.id == new_task_id)
    )).scalar_one()
    assert step2.attempt == 2
    assert step2.status == "pending"
    assert step2.step == "finder"


@pytest.mark.asyncio
async def test_fail_task_fatal_goes_to_manual_action(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(
            select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
        )
    ).scalar_one()

    task_service = TaskService(db_session, max_retries=3)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    new_task_id = await task_service.fail(
        task_id=task_id, error="fatal", retryable=False, request_id="r3"
    )

    assert new_task_id is None

    wf = (
        await db_session.execute(select(Workflow).where(Workflow.id == wf_id))
    ).scalar_one()
    assert wf.status == State.AWAITING_MANUAL_ACTION.value
    assert wf.failed_step == "finder"


@pytest.mark.asyncio
async def test_fail_task_retry_exhausted_goes_to_manual_action(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_service = TaskService(db_session, max_retries=2)

    for attempt in range(2):
        task_id = (
            await db_session.execute(
                select(StepExecution.id)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.attempt == attempt + 1)
            )
        ).scalar_one()
        await task_service.start(task_id=task_id, agent_id="a1", request_id="r")
        new_id = await task_service.fail(
            task_id=task_id, error="boom", retryable=True, request_id="r"
        )
        if attempt == 0:
            assert new_id is not None
        else:
            assert new_id is None  # 超过 max_retries=2

    wf = (await db_session.execute(
        select(Workflow).where(Workflow.id == wf_id)
    )).scalar_one()
    assert wf.status == State.AWAITING_MANUAL_ACTION.value


@pytest.mark.asyncio
async def test_heartbeat_updates_timestamp(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(
            select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
        )
    ).scalar_one()

    task_service = TaskService(db_session)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    before = (
        await db_session.execute(
            select(StepExecution.last_heartbeat_at).where(StepExecution.id == task_id)
        )
    ).scalar_one()

    await task_service.heartbeat(task_id=task_id, message="working on LLM call")

    after = (
        await db_session.execute(
            select(StepExecution.last_heartbeat_at).where(StepExecution.id == task_id)
        )
    ).scalar_one()
    assert after >= before
    msg = (
        await db_session.execute(
            select(StepExecution.heartbeat_message).where(StepExecution.id == task_id)
        )
    ).scalar_one()
    assert msg == "working on LLM call"
```

### Step 7.2: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_task_service.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 7.3: 实现 TaskService

- [ ] 创建 `scheduler/engine/task_service.py`：

```python
"""Task lifecycle service: start / complete / fail / heartbeat。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.engine.state_machine import State, transition
from scheduler.engine.workflow_service import WorkflowService
from scheduler.observability.logging import get_logger
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent

logger = get_logger(__name__)


class TaskService:
    def __init__(self, session: AsyncSession, *, max_retries: int = 3) -> None:
        self.session = session
        self.max_retries = max_retries

    async def start(
        self, *, task_id: uuid.UUID, agent_id: str, request_id: str
    ) -> None:
        step = await self._get_step(task_id)
        if step.status != "pending":
            logger.warning(
                "task.start.non_pending",
                task_id=str(task_id),
                status=step.status,
            )
            return
        now = datetime.now(timezone.utc)
        step.status = "running"
        step.agent_id = agent_id
        step.started_at = now
        step.last_heartbeat_at = now
        self.session.add(
            WorkflowEvent(
                workflow_id=step.workflow_id,
                event_type="task.started",
                payload={"task_id": str(task_id), "agent_id": agent_id},
                request_id=request_id,
            )
        )
        logger.info(
            "task.started",
            task_id=str(task_id),
            workflow_id=str(step.workflow_id),
            step=step.step,
            attempt=step.attempt,
            agent_id=agent_id,
        )

    async def complete(
        self, *, task_id: uuid.UUID, output: dict, request_id: str
    ) -> None:
        step = await self._get_step(task_id)
        if step.status != "running":
            logger.warning(
                "task.complete.non_running", task_id=str(task_id), status=step.status
            )
            return
        now = datetime.now(timezone.utc)
        step.status = "succeeded"
        step.output = output
        step.finished_at = now
        self.session.add(
            WorkflowEvent(
                workflow_id=step.workflow_id,
                event_type="task.succeeded",
                payload={"task_id": str(task_id), "output": output},
                request_id=request_id,
            )
        )
        logger.info(
            "task.succeeded",
            task_id=str(task_id),
            workflow_id=str(step.workflow_id),
            step=step.step,
        )
        await self.session.flush()

        # 驱动 workflow 到下一状态
        wf_service = WorkflowService(self.session, artifact_root="")
        await wf_service.advance_on_step_success(step.workflow_id, request_id=request_id)

    async def fail(
        self,
        *,
        task_id: uuid.UUID,
        error: str,
        retryable: bool,
        request_id: str,
    ) -> uuid.UUID | None:
        """失败处理。返回新的 pending task_id（如有重试），或 None（转人工介入）。"""
        step = await self._get_step(task_id)
        if step.status not in ("running", "pending"):
            logger.warning("task.fail.bad_status", task_id=str(task_id), status=step.status)
            return None
        now = datetime.now(timezone.utc)
        step.status = "failed"
        step.error = error
        step.finished_at = now
        self.session.add(
            WorkflowEvent(
                workflow_id=step.workflow_id,
                event_type="task.failed",
                payload={"task_id": str(task_id), "error": error, "retryable": retryable},
                request_id=request_id,
            )
        )
        logger.info(
            "task.failed",
            task_id=str(task_id),
            workflow_id=str(step.workflow_id),
            step=step.step,
            attempt=step.attempt,
            retryable=retryable,
        )

        if retryable and step.attempt < self.max_retries:
            return await self._retry(step, request_id=request_id)

        # 转人工介入
        wf = (
            await self.session.execute(
                select(Workflow).where(Workflow.id == step.workflow_id)
            )
        ).scalar_one()
        src = State(wf.status)
        transition(src, State.AWAITING_MANUAL_ACTION)
        wf.status = State.AWAITING_MANUAL_ACTION.value
        wf.failed_step = step.step
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": State.AWAITING_MANUAL_ACTION.value},
                request_id=request_id,
            )
        )
        logger.info(
            "workflow.manual_intervention",
            workflow_id=str(wf.id),
            failed_step=step.step,
        )
        return None

    async def heartbeat(
        self, *, task_id: uuid.UUID, message: str | None = None
    ) -> None:
        step = await self._get_step(task_id)
        step.last_heartbeat_at = datetime.now(timezone.utc)
        if message:
            step.heartbeat_message = message

    async def _retry(
        self, failed: StepExecution, *, request_id: str
    ) -> uuid.UUID:
        new_exec = StepExecution(
            workflow_id=failed.workflow_id,
            step=failed.step,
            attempt=failed.attempt + 1,
            status="pending",
            input=failed.input,
            request_id=request_id,
        )
        self.session.add(new_exec)
        # workflow 状态从 RUNNING 自转到 RUNNING（attempt+1）——state machine 允许 RUNNING->RUNNING
        self.session.add(
            WorkflowEvent(
                workflow_id=failed.workflow_id,
                event_type="task.retried",
                payload={
                    "previous_task_id": str(failed.id),
                    "new_task_id": str(new_exec.id),
                    "attempt": new_exec.attempt,
                },
                request_id=request_id,
            )
        )
        await self.session.flush()
        logger.info(
            "task.retried",
            workflow_id=str(failed.workflow_id),
            step=failed.step,
            new_attempt=new_exec.attempt,
        )
        return new_exec.id

    async def _get_step(self, task_id: uuid.UUID) -> StepExecution:
        result = await self.session.execute(
            select(StepExecution).where(StepExecution.id == task_id)
        )
        step = result.scalar_one_or_none()
        if step is None:
            raise ValueError(f"Task {task_id} not found")
        return step
```

### Step 7.4: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_task_service.py -v
```

Expected: 6 tests PASS

### Step 7.5: 提交

- [ ] 运行：

```bash
git add scheduler/engine/task_service.py scheduler/tests/test_task_service.py
git commit -m "feat(engine): TaskService lifecycle (start/complete/fail/heartbeat) with retry logic"
```

---

## Task 8: Approval Service（审批推进 / skip / rerun / abort）

**Files:**
- Create: `scheduler/engine/approval_service.py`
- Create: `scheduler/tests/test_approval_service.py`

### Step 8.1: 写失败测试

- [ ] 创建 `scheduler/tests/test_approval_service.py`：

```python
import uuid

import pytest
from sqlalchemy import select

from scheduler.engine.approval_service import ApprovalService
from scheduler.engine.state_machine import State
from scheduler.engine.task_service import TaskService
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.models import Approval, StepExecution, Workflow


async def _create_and_finish_first_step(
    db_session, *, approval_policy: dict
) -> tuple[uuid.UUID, uuid.UUID]:
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t",
        input={"topic": "x"},
        approval_policy=approval_policy,
        request_id="req_c",
    )
    task_id = (
        await db_session.execute(
            select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
        )
    ).scalar_one()
    ts = TaskService(db_session)
    await ts.start(task_id=task_id, agent_id="a1", request_id="r")
    await ts.complete(task_id=task_id, output={}, request_id="r")
    return wf_id, task_id


@pytest.mark.asyncio
async def test_approve_advances_from_awaiting_approval(db_session):
    # policy manual → FINDER_DONE → AWAITING_APPROVAL_REQUIREMENT
    wf_id, _ = await _create_and_finish_first_step(
        db_session, approval_policy={"requirement": "manual"}
    )
    wf = (
        await db_session.execute(select(Workflow).where(Workflow.id == wf_id))
    ).scalar_one()
    assert wf.status == State.AWAITING_APPROVAL_REQUIREMENT.value

    svc = ApprovalService(db_session)
    await svc.approve(
        workflow_id=wf_id, step="requirement", comment="ok", request_id="r2"
    )

    wf = (await db_session.execute(
        select(Workflow).where(Workflow.id == wf_id)
    )).scalar_one()
    assert wf.status == State.REQUIREMENT_RUNNING.value

    record = (await db_session.execute(
        select(Approval).where(Approval.workflow_id == wf_id)
    )).scalar_one()
    assert record.decision == "approve"
    assert record.step == "requirement"
    assert record.comment == "ok"


@pytest.mark.asyncio
async def test_reject_aborts_workflow(db_session):
    wf_id, _ = await _create_and_finish_first_step(
        db_session, approval_policy={"requirement": "manual"}
    )
    svc = ApprovalService(db_session)
    await svc.reject(workflow_id=wf_id, step="requirement", comment="bad", request_id="r2")

    wf = (await db_session.execute(
        select(Workflow).where(Workflow.id == wf_id)
    )).scalar_one()
    assert wf.status == State.ABORTED.value


@pytest.mark.asyncio
async def test_abort_any_state(db_session):
    # 用 auto 推进，workflow 在 REQUIREMENT_RUNNING 时强制 abort
    wf_id, _ = await _create_and_finish_first_step(
        db_session, approval_policy={"requirement": "auto"}
    )
    wf = (await db_session.execute(
        select(Workflow).where(Workflow.id == wf_id)
    )).scalar_one()
    assert wf.status == State.REQUIREMENT_RUNNING.value

    svc = ApprovalService(db_session)
    await svc.abort(workflow_id=wf_id, comment="stop", request_id="r2")

    wf = (await db_session.execute(
        select(Workflow).where(Workflow.id == wf_id)
    )).scalar_one()
    assert wf.status == State.ABORTED.value


@pytest.mark.asyncio
async def test_rerun_from_manual_action(db_session):
    # 制造 AWAITING_MANUAL_ACTION：失败+fatal
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", input={}, approval_policy={}, request_id="r"
    )
    task_id = (await db_session.execute(
        select(StepExecution.id).where(StepExecution.workflow_id == wf_id)
    )).scalar_one()
    ts = TaskService(db_session)
    await ts.start(task_id=task_id, agent_id="a", request_id="r")
    await ts.fail(task_id=task_id, error="x", retryable=False, request_id="r")

    svc = ApprovalService(db_session)
    new_task_id = await svc.rerun(
        workflow_id=wf_id,
        step="finder",
        modified_input=None,
        comment="retry",
        request_id="r2",
    )
    assert new_task_id is not None

    wf = (await db_session.execute(
        select(Workflow).where(Workflow.id == wf_id)
    )).scalar_one()
    assert wf.status == State.FINDER_RUNNING.value

    new_step = (await db_session.execute(
        select(StepExecution).where(StepExecution.id == new_task_id)
    )).scalar_one()
    assert new_step.status == "pending"
    assert new_step.step == "finder"
```

### Step 8.2: 运行测试确认失败

- [ ] 运行：

```bash
pytest scheduler/tests/test_approval_service.py -v
```

Expected: FAIL with `ModuleNotFoundError`

### Step 8.3: 实现 ApprovalService

- [ ] 创建 `scheduler/engine/approval_service.py`：

```python
"""Approval service: 审批 / reject / skip / rerun / abort。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.engine.state_machine import (
    STEPS,
    State,
    next_running_state,
    transition,
)
from scheduler.engine.workflow_service import WorkflowService
from scheduler.observability.logging import get_logger
from scheduler.storage.models import Approval, StepExecution, Workflow, WorkflowEvent

logger = get_logger(__name__)


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def approve(
        self, *, workflow_id: uuid.UUID, step: str, comment: str | None, request_id: str
    ) -> None:
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        target = next_running_state(src, policy=wf.approval_policy)
        transition(src, target)
        wf.status = target.value
        wf.current_step = target.value.removesuffix("_RUNNING").lower()
        self._record_approval(wf, decision="approve", step=step, comment=comment)
        self._record_event(wf, src=src, dst=target, request_id=request_id)
        if target.value.endswith("_RUNNING"):
            await self._enqueue_step(
                wf, step=target.value.removesuffix("_RUNNING").lower(), request_id=request_id
            )

    async def reject(
        self, *, workflow_id: uuid.UUID, step: str, comment: str | None, request_id: str
    ) -> None:
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        transition(src, State.ABORTED)
        wf.status = State.ABORTED.value
        self._record_approval(wf, decision="reject", step=step, comment=comment)
        self._record_event(wf, src=src, dst=State.ABORTED, request_id=request_id)

    async def abort(
        self, *, workflow_id: uuid.UUID, comment: str | None, request_id: str
    ) -> None:
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        transition(src, State.ABORTED)
        wf.status = State.ABORTED.value
        self._record_approval(wf, decision="abort", step=wf.current_step or "", comment=comment)
        self._record_event(wf, src=src, dst=State.ABORTED, request_id=request_id)

    async def rerun(
        self,
        *,
        workflow_id: uuid.UUID,
        step: str,
        modified_input: dict | None,
        comment: str | None,
        request_id: str,
    ) -> uuid.UUID:
        """从 AWAITING_MANUAL_ACTION 或 *_DONE 重跑指定 step。返回新 task_id。"""
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        target_running = State[f"{step.upper()}_RUNNING"]
        transition(src, target_running)
        wf.status = target_running.value
        wf.current_step = step
        wf.failed_step = None
        if modified_input is not None:
            wf.input = modified_input
        self._record_approval(
            wf,
            decision="rerun",
            step=step,
            comment=comment,
            payload={"modified_input": modified_input} if modified_input else None,
        )
        self._record_event(wf, src=src, dst=target_running, request_id=request_id)
        new_id = await self._enqueue_step(wf, step=step, request_id=request_id)
        return new_id

    async def skip(
        self, *, workflow_id: uuid.UUID, comment: str | None, request_id: str
    ) -> None:
        """跳过当前失败 step 推进到下一步（仅 AWAITING_MANUAL_ACTION 可用）。"""
        wf = await self._get_wf(workflow_id)
        if State(wf.status) != State.AWAITING_MANUAL_ACTION or not wf.failed_step:
            raise ValueError("skip only valid in AWAITING_MANUAL_ACTION with failed_step")
        failed_idx = STEPS.index(wf.failed_step)
        if failed_idx == len(STEPS) - 1:
            # 跳过最后一步 → COMPLETED
            target = State.COMPLETED
        else:
            next_step = STEPS[failed_idx + 1]
            policy = wf.approval_policy.get(next_step, "manual")
            if policy == "auto":
                target = State[f"{next_step.upper()}_RUNNING"]
            else:
                target = State[f"AWAITING_APPROVAL_{next_step.upper()}"]

        src = State(wf.status)
        transition(src, target)
        wf.status = target.value
        wf.failed_step = None
        self._record_approval(
            wf, decision="skip", step=STEPS[failed_idx], comment=comment
        )
        self._record_event(wf, src=src, dst=target, request_id=request_id)
        if target.value.endswith("_RUNNING"):
            await self._enqueue_step(
                wf, step=target.value.removesuffix("_RUNNING").lower(), request_id=request_id
            )

    async def _get_wf(self, workflow_id: uuid.UUID) -> Workflow:
        result = await self.session.execute(
            select(Workflow).where(Workflow.id == workflow_id)
        )
        wf = result.scalar_one_or_none()
        if wf is None:
            raise ValueError(f"Workflow {workflow_id} not found")
        return wf

    def _record_approval(
        self,
        wf: Workflow,
        *,
        decision: str,
        step: str,
        comment: str | None,
        payload: dict | None = None,
    ) -> None:
        self.session.add(
            Approval(
                workflow_id=wf.id,
                step=step,
                decision=decision,
                comment=comment,
                payload=payload,
            )
        )

    def _record_event(
        self, wf: Workflow, *, src: State, dst: State, request_id: str
    ) -> None:
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": dst.value},
                request_id=request_id,
            )
        )

    async def _enqueue_step(
        self, wf: Workflow, *, step: str, request_id: str
    ) -> uuid.UUID:
        result = await self.session.execute(
            select(StepExecution)
            .where(StepExecution.workflow_id == wf.id)
            .where(StepExecution.step == step)
        )
        existing = list(result.scalars().all())
        attempt = max((e.attempt for e in existing), default=0) + 1

        exec_ = StepExecution(
            workflow_id=wf.id,
            step=step,
            attempt=attempt,
            status="pending",
            input=wf.input,
            request_id=request_id,
        )
        self.session.add(exec_)
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="task.enqueued",
                payload={"step": step, "attempt": attempt, "task_id": str(exec_.id)},
                request_id=request_id,
            )
        )
        await self.session.flush()
        # TODO(M2): 在 session.commit 后 XADD 到 Redis Streams
        return exec_.id
```

### Step 8.4: 运行测试确认通过

- [ ] 运行：

```bash
pytest scheduler/tests/test_approval_service.py -v
```

Expected: 4 tests PASS

### Step 8.5: 提交

- [ ] 运行：

```bash
git add scheduler/engine/approval_service.py scheduler/tests/test_approval_service.py
git commit -m "feat(engine): ApprovalService for approve/reject/abort/rerun/skip"
```

---

## Task 9: API 层（Pydantic schemas + FastAPI 路由）

**Files:**
- Create: `scheduler/api/__init__.py`
- Create: `scheduler/api/schemas.py`
- Create: `scheduler/api/workflows.py`
- Create: `scheduler/api/tasks.py`
- Create: `scheduler/api/approvals.py`
- Create: `scheduler/api/agents.py`

### Step 9.1: 创建 API schemas（Pydantic 请求/响应模型）

- [ ] 创建 `scheduler/api/__init__.py`（空文件）

- [ ] 创建 `scheduler/api/schemas.py`：

```python
"""API 请求 / 响应 Pydantic 模型。"""
from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    input: dict
    approval_policy: dict = Field(default_factory=dict)


class WorkflowRead(BaseModel):
    id: uuid.UUID
    name: str
    status: str
    input: dict
    approval_policy: dict
    current_step: str | None
    failed_step: str | None
    artifact_root: str
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class TaskStartRequest(BaseModel):
    agent_id: str


class TaskCompleteRequest(BaseModel):
    output: dict = Field(default_factory=dict)


class TaskFailRequest(BaseModel):
    error: str
    retryable: bool = True


class TaskHeartbeatRequest(BaseModel):
    message: str | None = None


class ApprovalRequest(BaseModel):
    decision: str  # approve/reject/skip/rerun/abort
    step: str | None = None
    comment: str | None = None
    modified_input: dict | None = None


class AgentRegisterRequest(BaseModel):
    name: str
    step: str
    metadata: dict | None = None


class AgentRead(BaseModel):
    id: uuid.UUID
    name: str
    step: str
    status: str
    last_seen_at: datetime

    class Config:
        from_attributes = True
```

### Step 9.2: 创建共享 DB 依赖

- [ ] 追加到 `scheduler/api/__init__.py`：

```python
"""API 共享依赖。"""
from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.config import Settings, get_settings
from scheduler.storage.db import Database

_db_singleton: Database | None = None


def set_database(db: Database) -> None:
    global _db_singleton
    _db_singleton = db


def get_database() -> Database:
    if _db_singleton is None:
        raise RuntimeError("Database not initialized; call set_database in startup")
    return _db_singleton


async def get_session() -> AsyncIterator[AsyncSession]:
    db = get_database()
    async with db.session() as session:
        yield session


def settings_dep() -> Settings:
    return get_settings()
```

### Step 9.3: 创建 workflows 路由

- [ ] 创建 `scheduler/api/workflows.py`：

```python
"""/api/workflows endpoints。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session, settings_dep
from scheduler.api.schemas import WorkflowCreate, WorkflowRead
from scheduler.config import Settings
from scheduler.engine.workflow_service import WorkflowService
from scheduler.observability.logging import get_request_id

router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowRead, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> WorkflowRead:
    service = WorkflowService(session, artifact_root=settings.artifact_root)
    rid = get_request_id() or "req_unknown"
    wf_id = await service.create(
        name=body.name,
        input=body.input,
        approval_policy=body.approval_policy,
        request_id=rid,
    )
    wf = await service.get(wf_id)
    assert wf is not None
    return WorkflowRead.model_validate(wf)


@router.get("", response_model=list[WorkflowRead])
async def list_workflows(
    status: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=500),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> list[WorkflowRead]:
    service = WorkflowService(session, artifact_root=settings.artifact_root)
    items = await service.list(status=status, limit=limit)
    return [WorkflowRead.model_validate(i) for i in items]


@router.get("/{wf_id}", response_model=WorkflowRead)
async def get_workflow(
    wf_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> WorkflowRead:
    service = WorkflowService(session, artifact_root=settings.artifact_root)
    wf = await service.get(wf_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return WorkflowRead.model_validate(wf)
```

### Step 9.4: 创建 tasks 路由

- [ ] 创建 `scheduler/api/tasks.py`：

```python
"""/api/tasks endpoints（agent SDK 调用）。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session, settings_dep
from scheduler.api.schemas import (
    TaskCompleteRequest,
    TaskFailRequest,
    TaskHeartbeatRequest,
    TaskStartRequest,
)
from scheduler.config import Settings
from scheduler.engine.task_service import TaskService
from scheduler.observability.logging import get_request_id

router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.put("/{task_id}/start")
async def start_task(
    task_id: uuid.UUID,
    body: TaskStartRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> dict:
    svc = TaskService(session, max_retries=settings.max_retries)
    rid = get_request_id() or "req_unknown"
    await svc.start(task_id=task_id, agent_id=body.agent_id, request_id=rid)
    return {"ok": True}


@router.put("/{task_id}/complete")
async def complete_task(
    task_id: uuid.UUID,
    body: TaskCompleteRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> dict:
    svc = TaskService(session, max_retries=settings.max_retries)
    rid = get_request_id() or "req_unknown"
    await svc.complete(task_id=task_id, output=body.output, request_id=rid)
    return {"ok": True}


@router.put("/{task_id}/fail")
async def fail_task(
    task_id: uuid.UUID,
    body: TaskFailRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> dict:
    svc = TaskService(session, max_retries=settings.max_retries)
    rid = get_request_id() or "req_unknown"
    new_id = await svc.fail(
        task_id=task_id, error=body.error, retryable=body.retryable, request_id=rid
    )
    return {"ok": True, "new_task_id": str(new_id) if new_id else None}


@router.put("/{task_id}/heartbeat")
async def heartbeat(
    task_id: uuid.UUID,
    body: TaskHeartbeatRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    svc = TaskService(session)
    await svc.heartbeat(task_id=task_id, message=body.message)
    return {"ok": True}
```

### Step 9.5: 创建 approvals 路由

- [ ] 创建 `scheduler/api/approvals.py`：

```python
"""/api/workflows/<id>/approvals endpoints。"""
from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session
from scheduler.api.schemas import ApprovalRequest
from scheduler.engine.approval_service import ApprovalService
from scheduler.engine.state_machine import InvalidTransition
from scheduler.observability.logging import get_request_id

router = APIRouter(prefix="/api/workflows", tags=["approvals"])


@router.post("/{wf_id}/approvals")
async def submit_approval(
    wf_id: uuid.UUID,
    body: ApprovalRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    svc = ApprovalService(session)
    rid = get_request_id() or "req_unknown"
    try:
        if body.decision == "approve":
            if not body.step:
                raise HTTPException(400, "step required for approve")
            await svc.approve(
                workflow_id=wf_id, step=body.step, comment=body.comment, request_id=rid
            )
            return {"ok": True}
        if body.decision == "reject":
            if not body.step:
                raise HTTPException(400, "step required for reject")
            await svc.reject(
                workflow_id=wf_id, step=body.step, comment=body.comment, request_id=rid
            )
            return {"ok": True}
        if body.decision == "abort":
            await svc.abort(workflow_id=wf_id, comment=body.comment, request_id=rid)
            return {"ok": True}
        if body.decision == "rerun":
            if not body.step:
                raise HTTPException(400, "step required for rerun")
            new_id = await svc.rerun(
                workflow_id=wf_id,
                step=body.step,
                modified_input=body.modified_input,
                comment=body.comment,
                request_id=rid,
            )
            return {"ok": True, "new_task_id": str(new_id)}
        if body.decision == "skip":
            await svc.skip(workflow_id=wf_id, comment=body.comment, request_id=rid)
            return {"ok": True}
        raise HTTPException(400, f"Unknown decision: {body.decision}")
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
```

### Step 9.6: 创建 agents 路由

- [ ] 创建 `scheduler/api/agents.py`：

```python
"""/api/agents endpoints。"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session
from scheduler.api.schemas import AgentRead, AgentRegisterRequest
from scheduler.observability.logging import get_logger
from scheduler.storage.models import Agent

logger = get_logger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.post("/register", response_model=AgentRead)
async def register_agent(
    body: AgentRegisterRequest,
    session: AsyncSession = Depends(get_session),
) -> AgentRead:
    now = datetime.now(timezone.utc)
    agent = Agent(
        id=uuid.uuid4(),
        name=body.name,
        step=body.step,
        status="online",
        last_seen_at=now,
        metadata_=body.metadata,
    )
    session.add(agent)
    await session.flush()
    logger.info("agent.registered", agent_id=str(agent.id), name=body.name, step=body.step)
    return AgentRead.model_validate(agent)


@router.get("", response_model=list[AgentRead])
async def list_agents(session: AsyncSession = Depends(get_session)) -> list[AgentRead]:
    result = await session.execute(select(Agent).order_by(Agent.last_seen_at.desc()))
    return [AgentRead.model_validate(a) for a in result.scalars().all()]
```

### Step 9.7: 提交

- [ ] 运行：

```bash
git add scheduler/api
git commit -m "feat(api): Pydantic schemas + FastAPI routers for workflows/tasks/approvals/agents"
```

---

## Task 10: 主应用入口 + 集成测试

**Files:**
- Create: `scheduler/main.py`
- Create: `scheduler/tests/test_api.py`

### Step 10.1: 创建 main.py

- [ ] 创建 `scheduler/main.py`：

```python
"""FastAPI 应用入口。"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from scheduler.api import set_database
from scheduler.api.agents import router as agents_router
from scheduler.api.approvals import router as approvals_router
from scheduler.api.tasks import router as tasks_router
from scheduler.api.workflows import router as workflows_router
from scheduler.config import get_settings
from scheduler.observability.logging import configure_logging, get_logger
from scheduler.observability.middleware import RequestIdMiddleware
from scheduler.storage.db import Database


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(level=settings.log_level, format=settings.log_format)
    logger = get_logger(__name__)

    database = Database(settings)
    set_database(database)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        logger.info("scheduler.starting")
        yield
        await database.dispose()
        logger.info("scheduler.stopped")

    app = FastAPI(
        title="AIClusterSchedule Scheduler",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(workflows_router)
    app.include_router(tasks_router)
    app.include_router(approvals_router)
    app.include_router(agents_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    return app


app = create_app()
```

### Step 10.2: 写 API 集成测试

- [ ] 创建 `scheduler/tests/test_api.py`：

```python
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from scheduler.api import set_database
from scheduler.main import create_app


@pytest_asyncio.fixture
async def client(database):
    set_database(database)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_workflow_returns_finder_running(client):
    r = await client.post(
        "/api/workflows",
        json={"name": "wf1", "input": {"topic": "x"}, "approval_policy": {}},
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "FINDER_RUNNING"
    assert body["current_step"] == "finder"


@pytest.mark.asyncio
async def test_full_step_lifecycle_through_api(client, database):
    """端到端：create workflow → agent 接管 → start/complete → workflow 自动推进到下一步。"""
    from sqlalchemy import select

    from scheduler.storage.models import StepExecution, Workflow

    # 1) create
    r = await client.post(
        "/api/workflows",
        json={
            "name": "t",
            "input": {"topic": "x"},
            "approval_policy": {"requirement": "auto"},
        },
    )
    assert r.status_code == 201
    wf_id = r.json()["id"]

    # 2) agent register
    r = await client.post(
        "/api/agents/register", json={"name": "ai-finder-01", "step": "finder"}
    )
    assert r.status_code == 200

    # 3) 直接查 DB 拿 pending finder task_id
    async with database.session() as s:
        task_id = (
            await s.execute(
                select(StepExecution.id)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.step == "finder")
            )
        ).scalar_one()

    # 4) task start
    r = await client.put(
        f"/api/tasks/{task_id}/start", json={"agent_id": "ai-finder-01"}
    )
    assert r.status_code == 200

    # 5) task complete → workflow 应该 auto 推进到 REQUIREMENT_RUNNING
    r = await client.put(
        f"/api/tasks/{task_id}/complete", json={"output": {"idea_summary": "s"}}
    )
    assert r.status_code == 200

    r = await client.get(f"/api/workflows/{wf_id}")
    assert r.json()["status"] == "REQUIREMENT_RUNNING"
    assert r.json()["current_step"] == "requirement"

    # 6) DB 应有 requirement 的 pending task_execution
    async with database.session() as s:
        req_tasks = (
            await s.execute(
                select(StepExecution)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.step == "requirement")
            )
        ).scalars().all()
        assert len(req_tasks) == 1
        assert req_tasks[0].status == "pending"


@pytest.mark.asyncio
async def test_request_id_echoed_in_response_header(client):
    r = await client.post(
        "/api/workflows",
        json={"name": "r", "input": {}, "approval_policy": {}},
        headers={"X-Request-ID": "req_custom"},
    )
    assert r.headers.get("X-Request-ID") == "req_custom"


@pytest.mark.asyncio
async def test_list_workflows_filter_by_status(client):
    await client.post(
        "/api/workflows", json={"name": "a", "input": {}, "approval_policy": {}}
    )
    await client.post(
        "/api/workflows", json={"name": "b", "input": {}, "approval_policy": {}}
    )
    r = await client.get("/api/workflows?status=FINDER_RUNNING&limit=10")
    assert r.status_code == 200
    items = r.json()
    assert len(items) >= 2
    assert all(i["status"] == "FINDER_RUNNING" for i in items)


@pytest.mark.asyncio
async def test_approve_invalid_state_returns_409(client):
    r = await client.post(
        "/api/workflows",
        json={"name": "r", "input": {}, "approval_policy": {}},
    )
    wf_id = r.json()["id"]
    # workflow 在 FINDER_RUNNING 状态，无法直接 approve
    r = await client.post(
        f"/api/workflows/{wf_id}/approvals",
        json={"decision": "approve", "step": "requirement"},
    )
    assert r.status_code == 409
```

### Step 10.3: 运行全部测试

- [ ] 运行：

```bash
make test
```

Expected: 所有已有测试 + 新 API 测试 PASS，覆盖率 >= 80%

### Step 10.4: 手动验证服务可启动

- [ ] 启动服务（假设本地 Postgres 已运行、`.env` 已配置）：

```bash
make migrate
make run
```

- [ ] 在另一个终端验证：

```bash
curl -v http://localhost:8000/health
# Expected: 200 {"status":"ok"}, 响应头有 X-Request-ID

curl -X POST http://localhost:8000/api/workflows \
  -H "Content-Type: application/json" \
  -d '{"name":"smoke","input":{"topic":"test"},"approval_policy":{}}'
# Expected: 201 with workflow JSON, status=FINDER_RUNNING
```

- [ ] 查看日志，确认每行都是 JSON 格式、包含 `request_id`

- [ ] `Ctrl+C` 停止服务

### Step 10.5: 提交

- [ ] 运行：

```bash
git add scheduler/main.py scheduler/tests/test_api.py
git commit -m "feat(main): FastAPI app entrypoint + API integration tests"
```

---

## Task 11: 里程碑收尾

### Step 11.1: 运行完整测试套件 + 覆盖率

- [ ] 运行：

```bash
make test
```

Expected: 所有测试 PASS，覆盖率输出显示：
- `scheduler.engine.*` ≥ 90%
- 整体 ≥ 80%

如果 engine 模块覆盖率 < 90%，回到相应 Task 补测试；不要开始 M2。

### Step 11.2: 运行 lint 和 type check

- [ ] 运行：

```bash
make lint
make type
```

Expected: 无错误。如有 mypy 错误，修复后重跑。

### Step 11.3: 写 README 起步段落

- [ ] 创建或更新 `README.md`，内容：

```markdown
# AIClusterSchedule

AI 端到端软件交付流水线调度平台（M1: Scheduler 后端骨架）。

详见 `docs/superpowers/specs/2026-04-20-aiclusterschedule-design.md`。

## M1 开发启动

```bash
# 1. 起 Postgres
docker run -d --name aijuicer-pg -e POSTGRES_USER=aijuicer \
  -e POSTGRES_PASSWORD=aijuicer -e POSTGRES_DB=aijuicer \
  -p 5432:5432 postgres:15

# 2. 依赖
python3.11 -m venv .venv && source .venv/bin/activate
make install
cp .env.example .env

# 3. 迁移 + 启动
make migrate
make run

# 4. 健康检查
curl http://localhost:8000/health
```

## 里程碑

- **M1** ✅ 后端骨架 + 状态机 + 核心 API + 结构化日志
- M2 Agent Python SDK
- M3 可恢复性（重试/超时/启动恢复）+ Redis Streams 接入
- M4 审批与人工介入 UI 操作
- M5 Web UI v1
- M6 产物预览
- M7 6 示例 agent + Docker Compose
- M8 可观测性（Prometheus）

## 测试

```bash
make test    # pytest + coverage
make lint    # ruff
make type    # mypy
```
```

### Step 11.4: 提交

- [ ] 运行：

```bash
git add README.md
git commit -m "docs: M1 README with setup and milestones"
```

### Step 11.5: 标记里程碑

- [ ] 创建 tag：

```bash
git tag m1-scheduler-backbone -m "M1: Scheduler backbone (state machine + core API + structured logging)"
```

---

## 里程碑完成标准（验证清单）

M1 完成，下面每一项都必须能演示：

- [ ] `make test` 全绿；`scheduler.engine.*` 覆盖率 ≥ 90%，整体 ≥ 80%
- [ ] `make lint` `make type` 无错
- [ ] `make migrate` 成功在干净 Postgres 上建出 6 张表 + alembic_version
- [ ] `make run` 启动后 `GET /health` 返回 200
- [ ] `POST /api/workflows` 创建后：DB 中 status=FINDER_RUNNING，step_executions 一条 pending 记录，workflow_events 三条（created/state.changed/task.enqueued）
- [ ] 通过 API 跑完单个 step 的 `start → complete` 后，workflow 进入下一态（auto policy）或 AWAITING_APPROVAL（manual policy）
- [ ] fail(retryable=True) 创建 attempt+1 的新 pending 记录；fail(retryable=False) 或重试耗尽后 workflow 转 AWAITING_MANUAL_ACTION
- [ ] POST approval 为 approve 可推进；reject/abort 可终止
- [ ] 所有日志为 JSON、含 `timestamp/level/message/request_id`
- [ ] `X-Request-ID` 请求头能被沿用或自动生成，并原样返回

## 后续里程碑预览

M1 完成后，M2 的 plan 将聚焦：
- Redis Streams 集成（把 M1 留的 `TODO(M2) XADD` 钩子落实）
- Agent Python SDK 的 `@agent.handler` 装饰器 + `ctx` 对象
- Agent ↔ Scheduler 的 HTTP 调用封装 + 心跳后台协程
- 产物 save/load API + 文件系统存储
- 端到端 demo agent（echo agent）

每个后续里程碑都会独立开 plan。
