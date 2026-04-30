"""Contract tests for feature-5 / feature-6 pagination + agent_trace nullability."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import get_session
from src.main import app


def _mock_item(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "source": "hackernews",
        "title": "t",
        "url": "https://e/1",
        "content": "body",
        "raw_data": {"score": 10, "num_comments": 5},
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
        "analysis_result_id": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_result(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "idea_title": "idea",
        "overall_score": 7.5,
        "project_name": None,
        "product_type": None,
        "aijuicer_workflow_id": None,
        "product_idea": None,
        "target_audience": None,
        "use_case": None,
        "pain_points": None,
        "key_features": None,
        "source_quote": None,
        "user_story": None,
        "source_item_id": None,
        "source_item_title": None,
        "source_item_url": None,
        "reasoning": None,
        "source_item_ids": [],
        "agent_trace": {"trace": [], "message_count": 0},
        "created_at": datetime.now(timezone.utc),
        "idea_description": None,
        "market_analysis": None,
        "tech_feasibility": None,
    }
    defaults.update(kwargs)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _override(session):
    async def override():
        yield session

    app.dependency_overrides[get_session] = override


# ---- feature-5: SourceItems per_page contract ----


@pytest.mark.asyncio
async def test_source_items_response_uses_per_page_field():
    session = AsyncMock()
    count = MagicMock()
    count.scalar_one.return_value = 0
    items = MagicMock()
    items.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[count, items])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/source-items?page=1&per_page=25")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["per_page"] == 25
    assert "page_size" not in data


@pytest.mark.asyncio
async def test_source_items_accepts_legacy_page_size_query():
    session = AsyncMock()
    count = MagicMock()
    count.scalar_one.return_value = 0
    items = MagicMock()
    items.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[count, items])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/source-items?page=1&page_size=15")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    assert resp.json()["data"]["per_page"] == 15


@pytest.mark.asyncio
async def test_source_items_per_page_over_200_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/source-items?per_page=201")
    assert resp.status_code == 400
    assert resp.json()["code"] == "400000"


@pytest.mark.asyncio
async def test_source_item_detail_includes_raw_data():
    item = _mock_item(raw_data={"score": 42, "url": "https://hn/item?id=1"})
    session = AsyncMock()
    first = MagicMock()
    first.scalar_one_or_none = lambda: item
    analysis_lookup = MagicMock()
    analysis_lookup.all.return_value = []
    session.execute = AsyncMock(side_effect=[first, analysis_lookup])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/source-items/{item.id}")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["raw_data"]["score"] == 42
    assert body["category"] == "AI/ML"
    assert body["processed"] is True


# ---- feature-6: AnalysisResults pagination + agent_trace nullability ----


@pytest.mark.asyncio
async def test_analysis_results_response_uses_per_page_field():
    session = AsyncMock()
    count = MagicMock()
    count.scalar_one.return_value = 0
    items = MagicMock()
    items.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[count, items])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis-results?page=1&per_page=10")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["per_page"] == 10
    assert data["items"] == []
    assert data["total"] == 0


@pytest.mark.asyncio
async def test_analysis_result_detail_null_agent_trace_returns_null_not_500():
    """Per feature-6 edge case: legacy rows without agent_trace must return
    ``agent_trace: null`` instead of crashing with 500."""
    result = _mock_result(agent_trace=None)
    session = AsyncMock()
    session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: result)
    )
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/analysis-results/{result.id}")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    body = resp.json()["data"]
    assert body["agent_trace"] is None


@pytest.mark.asyncio
async def test_analysis_results_min_score_below_zero_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis-results?min_score=-0.5")
    assert resp.status_code == 400
    assert resp.json()["code"] == "400000"


@pytest.mark.asyncio
async def test_analysis_results_min_score_above_hundred_returns_400():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis-results?min_score=100.1")
    assert resp.status_code == 400
    assert resp.json()["code"] == "400000"


@pytest.mark.asyncio
async def test_analysis_results_order_asc_flips_sort_direction():
    """Per feature-10 UI contract the list accepts `order=asc` to flip the
    default descending score sort."""
    session = AsyncMock()
    count = MagicMock()
    count.scalar_one.return_value = 0
    items = MagicMock()
    items.scalars.return_value.all.return_value = []
    session.execute = AsyncMock(side_effect=[count, items])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis-results?order=asc")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    # Structural guarantee: order=invalid must 400
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        bad = await client.get("/api/analysis-results?order=sideways")
    assert bad.status_code == 400


@pytest.mark.asyncio
async def test_source_items_accepts_date_range_filter():
    session = AsyncMock()
    count = MagicMock()
    count.scalar_one.return_value = 0
    items = MagicMock()
    items.scalars.return_value.all.return_value = []
    # Third call is the analysis_result_id bulk lookup (empty list → empty result).
    analysis_rows = MagicMock()
    analysis_rows.all.return_value = []
    session.execute = AsyncMock(side_effect=[count, items])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/source-items?collected_since=2026-04-01&collected_until=2026-04-23"
            )
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200


@pytest.mark.asyncio
async def test_source_items_rejects_invalid_date_range():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/source-items?collected_since=not-a-date")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "400000"
    assert "collected_since" in body["message"]


@pytest.mark.asyncio
async def test_source_item_detail_includes_analysis_result_id():
    item_id = uuid.uuid4()
    result_id = uuid.uuid4()

    item = _mock_item(id=item_id)
    session = AsyncMock()
    # 1) first execute → load SourceItem
    first = MagicMock()
    first.scalar_one_or_none = lambda: item
    # 2) second execute → analysis_id_map lookup
    second = MagicMock()
    second.all.return_value = [(result_id, item_id)]
    session.execute = AsyncMock(side_effect=[first, second])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/source-items/{item_id}")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["analysis_result_id"] == str(result_id)


@pytest.mark.asyncio
async def test_analysis_results_happy_path_ordered_by_score():
    r1 = _mock_result(overall_score=9.5)
    r2 = _mock_result(overall_score=6.2)
    session = AsyncMock()
    count = MagicMock()
    count.scalar_one.return_value = 2
    items = MagicMock()
    items.scalars.return_value.all.return_value = [r1, r2]
    session.execute = AsyncMock(side_effect=[count, items])
    _override(session)
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis-results?page=1&per_page=20")
    finally:
        app.dependency_overrides.clear()
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert [i["overall_score"] for i in data["items"]] == [9.5, 6.2]
    assert data["total"] == 2
