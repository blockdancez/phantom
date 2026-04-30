import pytest
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from httpx import AsyncClient, ASGITransport

from app.middleware import RequestIdMiddleware


@pytest.fixture
def app_with_middleware():
    app = FastAPI()

    app.add_middleware(RequestIdMiddleware)

    @app.get("/test")
    async def test_endpoint(request: Request):
        return JSONResponse({"request_id": request.state.request_id})

    return app


@pytest.mark.asyncio
async def test_request_id_is_set(app_with_middleware):
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test")

    assert response.status_code == 200
    body = response.json()
    assert "request_id" in body
    assert len(body["request_id"]) == 36


@pytest.mark.asyncio
async def test_request_id_in_response_header(app_with_middleware):
    transport = ASGITransport(app=app_with_middleware)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/test")

    assert "X-Request-ID" in response.headers
    assert len(response.headers["X-Request-ID"]) == 36
