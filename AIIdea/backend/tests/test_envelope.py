"""Confirm the unified envelope handles unhandled exceptions gracefully."""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from src.envelope import EnvelopeMiddleware, register_exception_handlers
from src.exceptions import APIError
from src.middleware import RequestIdMiddleware


def _build_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(EnvelopeMiddleware)
    app.add_middleware(RequestIdMiddleware)
    register_exception_handlers(app)

    @app.get("/api/boom")
    async def _boom():
        raise RuntimeError("test crash")

    @app.get("/api/api-error")
    async def _api_error():
        raise APIError("TEST001", "bad thing", http_status=418, data={"hint": "coffee"})

    @app.get("/api/ok")
    async def _ok():
        return {"hello": "world"}

    return app


@pytest.mark.asyncio
async def test_unhandled_exception_maps_to_envelope_500():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/boom")
    assert resp.status_code == 500
    body = resp.json()
    assert body["code"] == "999999"
    assert body["message"] == "internal server error"
    assert body["request_id"]


@pytest.mark.asyncio
async def test_api_error_passes_through_fields():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/api-error")
    assert resp.status_code == 418
    body = resp.json()
    assert body["code"] == "TEST001"
    assert body["message"] == "bad thing"
    assert body["data"] == {"hint": "coffee"}


@pytest.mark.asyncio
async def test_success_response_is_wrapped():
    app = _build_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/ok")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["message"] == "success"
    assert body["data"] == {"hello": "world"}
