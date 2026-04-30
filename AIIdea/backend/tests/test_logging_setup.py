"""Semi-structured logging configuration tests."""

from __future__ import annotations

import logging

from src.logging_setup import (
    SERVICE_NAME,
    _inject_service_name,
    _semi_structured_renderer,
    setup_logging,
)


def test_service_name_constant_matches_plan():
    assert SERVICE_NAME == "ai-idea-api"


def test_inject_service_name_adds_field_when_missing():
    event = {"event": "hi"}
    out = _inject_service_name(None, None, event)
    assert out["service_name"] == "ai-idea-api"


def test_inject_service_name_preserves_override():
    event = {"event": "hi", "service_name": "override-service"}
    out = _inject_service_name(None, None, event)
    assert out["service_name"] == "override-service"


def test_renderer_outputs_semi_structured_line():
    line = _semi_structured_renderer(
        None,
        None,
        {
            "timestamp": "2026-04-30T01:02:03.456Z",
            "level": "info",
            "thread_name": "MainThread",
            "logger": "src.api.pipeline",
            "event": "request_started",
            "request_id": "rid-1",
            "service_name": "ai-idea-api",
            "method": "GET",
            "path": "/api/health",
        },
    )
    # Mandatory header order: ts LEVEL [thread] logger - event
    assert line.startswith("2026-04-30T01:02:03.456Z  INFO ")
    assert "[MainThread]" in line
    assert "src.api.pipeline" in line
    assert "-  request_started" in line
    # Optional kv segment carries request_id + service_name + caller fields
    assert "request_id=rid-1" in line
    assert "service_name=ai-idea-api" in line
    assert "method=GET" in line
    assert "path=/api/health" in line


def test_renderer_quotes_values_with_spaces():
    line = _semi_structured_renderer(
        None,
        None,
        {
            "timestamp": "T",
            "level": "warning",
            "logger": "x",
            "event": "evt",
            "msg": "hello world",
        },
    )
    assert 'msg="hello world"' in line


def test_renderer_appends_exception_block():
    line = _semi_structured_renderer(
        None,
        None,
        {
            "timestamp": "T",
            "level": "error",
            "logger": "x",
            "event": "boom",
            "error_type": "RuntimeError",
            "exception": "Traceback (most recent call last):\n  File ...\nRuntimeError: boom",
        },
    )
    assert "error_type=RuntimeError" in line
    assert "Traceback" in line
    # exception block lives on its own following lines
    assert "\nTraceback" in line


def test_setup_logging_sets_level():
    setup_logging("WARNING")
    assert logging.getLogger().level == logging.WARNING
    setup_logging("INFO")
