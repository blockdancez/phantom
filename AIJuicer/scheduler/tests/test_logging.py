import json
from io import StringIO

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from scheduler.observability.logging import (
    bind_request_id,
    clear_request_id,
    configure_logging,
    get_logger,
    get_request_id,
)
from scheduler.observability.middleware import RequestIdMiddleware


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
    assert "request_id" not in second


def test_get_request_id_returns_bound_value(_configure_structlog_for_test):
    bind_request_id("req_xyz")
    assert get_request_id() == "req_xyz"


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


def test_reset_request_id_restores_parent_scope(_configure_structlog_for_test):
    from scheduler.observability.logging import (
        bind_request_id,
        reset_request_id,
    )

    token_outer = bind_request_id("req_outer")
    token_inner = bind_request_id("req_inner")
    assert get_request_id() == "req_inner"
    reset_request_id(token_inner)
    assert get_request_id() == "req_outer"
    reset_request_id(token_outer)
    assert get_request_id() is None


def test_invalid_log_level_raises(_configure_structlog_for_test):
    from scheduler.observability.logging import configure_logging

    with pytest.raises(ValueError):
        configure_logging(level="INVALID")


def test_request_id_scope_context_manager(_configure_structlog_for_test):
    from scheduler.observability.logging import request_id_scope

    with request_id_scope("req_scoped"):
        assert get_request_id() == "req_scoped"
    assert get_request_id() is None


def test_kv_format_emits_semi_structured_line():
    """半结构化格式：固定列（时间/级别/线程/logger/消息）+ 排序后的 k=v。"""
    buf = StringIO()
    configure_logging(level="INFO", format="kv", stream=buf)
    try:
        bind_request_id("req_kv")
        get_logger("scheduler.api.workflows").info(
            "workflow.created", workflow_id="wf-1", user_id="u-9"
        )
    finally:
        clear_request_id()

    line = buf.getvalue().strip().splitlines()[-1]
    # LEVEL 段补齐到 5 字符，所以 INFO 后面有一个空格
    assert " INFO  [MainThread] scheduler.api.workflows workflow.created" in line
    assert "request_id=req_kv" in line
    assert "user_id=u-9" in line
    assert "workflow_id=wf-1" in line


def test_kv_format_records_error_type_and_traceback():
    buf = StringIO()
    configure_logging(level="INFO", format="kv", stream=buf)
    try:
        raise ValueError("boom")
    except ValueError:
        get_logger("scheduler.test").exception("task.failed", task_id="t-1")

    out = buf.getvalue()
    # 一行 kv + 多行 traceback
    assert "error_type=ValueError" in out
    assert "Traceback (most recent call last):" in out
    assert "ValueError: boom" in out


def test_log_file_writes_alongside_console(tmp_path):
    log_file = tmp_path / "sub" / "scheduler.log"
    buf = StringIO()
    configure_logging(level="INFO", format="kv", stream=buf, log_file=log_file)
    get_logger("scheduler.test").info("boot", component="api")

    assert "boot" in buf.getvalue()
    assert log_file.exists()
    on_disk = log_file.read_text()
    assert "boot" in on_disk
    assert "component=api" in on_disk


def test_invalid_log_format_raises():
    with pytest.raises(ValueError):
        configure_logging(level="INFO", format="bogus")
