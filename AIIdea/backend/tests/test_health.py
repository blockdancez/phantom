"""Tests for /api/health + the unified envelope + global exception handlers.

We mock the underlying DB session so the test doesn't need an actual
Postgres instance running.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import health as health_module
from src.envelope import make_response
from src.exceptions import APIError
from src.main import app


@pytest.fixture
def db_session_ok(monkeypatch: pytest.MonkeyPatch):
    """Factory returning an AsyncMock session that returns from SELECT 1."""

    session = AsyncMock()
    session.execute = AsyncMock(return_value=AsyncMock())

    class _Ctx:
        async def __aenter__(self):
            return session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _factory():
        return lambda: _Ctx()

    monkeypatch.setattr(health_module, "get_async_session_factory", _factory)
    return session


@pytest.fixture
def db_session_fail(monkeypatch: pytest.MonkeyPatch):
    class _Ctx:
        async def __aenter__(self):
            raise RuntimeError("no db")

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _factory():
        return lambda: _Ctx()

    monkeypatch.setattr(health_module, "get_async_session_factory", _factory)


@pytest.mark.asyncio
async def test_health_envelope_success(db_session_ok):
    # No scheduler attached in test lifespan; health reports scheduler=fail
    # but DB is OK. Overall envelope still returns 200 with code 000000.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["message"] == "success"
    assert body["data"]["db"] == "ok"
    assert isinstance(body["request_id"], str) and body["request_id"]


@pytest.mark.asyncio
async def test_health_db_fail_returns_503(db_session_fail):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "HEALTH001"
    assert body["data"]["db"] == "fail"
    assert body["request_id"]


@pytest.mark.asyncio
async def test_request_id_header_returned(db_session_ok):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/health", headers={"X-Request-ID": "abc-123"})
    assert resp.headers["x-request-id"] == "abc-123"
    assert resp.json()["request_id"] == "abc-123"


@pytest.mark.asyncio
async def test_unknown_path_returns_envelope_404():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/does/not/exist")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "404000"
    assert "request_id" in body


def test_make_response_shape():
    resp = make_response({"x": 1}, "req-1")
    body = resp.body.decode()
    assert '"code":"000000"' in body
    assert '"request_id":"req-1"' in body


def test_api_error_fields():
    err = APIError("X001", "nope", http_status=418, data={"k": "v"})
    assert err.code == "X001"
    assert err.message == "nope"
    assert err.http_status == 418
    assert err.data == {"k": "v"}
