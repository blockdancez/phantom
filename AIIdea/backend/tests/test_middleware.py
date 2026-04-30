"""Tests for RequestIdMiddleware body logging + request_id propagation.

Per the project's backend coding standards, every request logs its body
(truncated at 1 KB) and the middleware must propagate the request_id via
structlog contextvars and the X-Request-ID response header.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.middleware import RequestIdMiddleware, _truncate


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(RequestIdMiddleware)

    @app.get("/echo")
    async def _echo():
        return {"ok": True}

    @app.post("/echo")
    async def _echo_post(payload: dict):
        return {"got": payload}

    return app


@pytest.mark.asyncio
async def test_middleware_generates_request_id_when_missing(caplog):
    app = _build_app()
    transport = ASGITransport(app=app)
    with caplog.at_level("INFO"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/echo")
    assert resp.status_code == 200
    assert "x-request-id" in resp.headers
    assert len(resp.headers["x-request-id"]) >= 8


@pytest.mark.asyncio
async def test_middleware_preserves_incoming_request_id():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/echo", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"


@pytest.mark.asyncio
async def test_middleware_logs_request_and_response_bodies(caplog):
    app = _build_app()
    transport = ASGITransport(app=app)
    with caplog.at_level("INFO"):
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/echo", json={"hello": "world"})
    assert resp.status_code == 200
    messages = " ".join(rec.message for rec in caplog.records)
    assert "请求开始" in messages
    assert "请求结束" in messages
    assert "request_body" in messages
    assert "response_body" in messages


@pytest.mark.asyncio
async def test_middleware_post_body_still_reaches_handler():
    """The middleware must re-seed the ASGI receive channel so POST bodies
    arrive at the handler even after we buffered them for logging."""
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/echo", json={"k": "v"})
    assert resp.status_code == 200
    assert resp.json() == {"got": {"k": "v"}}


def test_truncate_keeps_small_bodies_intact():
    assert _truncate(b"hi") == "hi"
    assert _truncate(b"") == ""


def test_truncate_caps_large_bodies():
    big = b"x" * 4096
    truncated = _truncate(big)
    assert truncated.startswith("x" * 1024)
    assert "truncated" in truncated
    assert len(truncated) <= 1024 + 40  # cap + short suffix


def test_truncate_handles_invalid_utf8_gracefully():
    out = _truncate(b"\xff\xfe\xfd\x00")
    assert isinstance(out, str)
