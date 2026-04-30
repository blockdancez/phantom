from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import get_session
from src.main import app


def _make_mock_item(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "source": "hackernews",
        "title": "Test Item",
        "url": "https://example.com/1",
        "content": "Some content",
        "raw_data": {},
        "category": "AI/ML",
        "tags": ["ai"],
        "score": 8.0,
        "summary_zh": None,
        "problem": None,
        "opportunity": None,
        "target_user": None,
        "why_now": None,
        "collected_at": datetime.now(timezone.utc),
        "processed": True,
        "created_at": datetime.now(timezone.utc),
        # pydantic's ``from_attributes`` would otherwise auto-pick up this
        # field as a MagicMock and fail UUID validation. The endpoint
        # overwrites it after validation from the separate analysis lookup.
        "analysis_result_id": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _override_session(mock_session):
    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override


@pytest.mark.asyncio
async def test_list_source_items_wraps_envelope():
    mock_items = [_make_mock_item()]
    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 1
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = mock_items
    # Third call is the bulk analysis_result_id lookup (no matches here).
    analysis_lookup = MagicMock()
    analysis_lookup.all.return_value = []
    mock_session.execute = AsyncMock(
        side_effect=[count_result, items_result, analysis_lookup]
    )
    _override_session(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/source-items?page=1&per_page=20")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["message"] == "success"
    assert body["data"]["total"] == 1
    assert len(body["data"]["items"]) == 1
    assert body["request_id"]


@pytest.mark.asyncio
async def test_list_source_items_empty_pagination_overflow():
    mock_session = AsyncMock()
    count_result = MagicMock()
    count_result.scalar_one.return_value = 0
    items_result = MagicMock()
    items_result.scalars.return_value.all.return_value = []
    mock_session.execute = AsyncMock(side_effect=[count_result, items_result])
    _override_session(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/source-items?page=9999&per_page=20")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["items"] == []
    assert body["data"]["total"] == 0
    assert body["data"]["page"] == 9999


@pytest.mark.asyncio
async def test_list_source_items_invalid_page_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/source-items?page=0&per_page=1")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "400000"
    assert body["data"]["errors"]


@pytest.mark.asyncio
async def test_list_source_items_invalid_page_size_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/source-items?page=1&per_page=9999")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "400000"


@pytest.mark.asyncio
async def test_get_source_item_not_found_returns_404_src001():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: None)
    )
    _override_session(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                f"/api/source-items/{uuid.uuid4()}",
            )
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "SRC001"
    assert body["message"] == "source item not found"


@pytest.mark.asyncio
async def test_get_source_item_invalid_uuid_returns_400_src002():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/source-items/not-a-uuid")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "SRC002"


@pytest.mark.asyncio
async def test_get_source_item_happy_path():
    item = _make_mock_item()
    mock_session = AsyncMock()
    first = MagicMock()
    first.scalar_one_or_none = lambda: item
    analysis_lookup = MagicMock()
    analysis_lookup.all.return_value = []
    mock_session.execute = AsyncMock(side_effect=[first, analysis_lookup])
    _override_session(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/source-items/{item.id}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["id"] == str(item.id)
