from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.db import get_session
from src.main import app


def _make_mock_result(**kwargs):
    defaults = {
        "id": uuid.uuid4(),
        "idea_title": "AI Code Buddy",
        "idea_description": None,
        "market_analysis": None,
        "tech_feasibility": None,
        "project_name": None,
        "product_type": None,
        "aijuicer_workflow_id": None,
        "product_idea": "An AI-powered pair programming tool.",
        "target_audience": "Developers",
        "use_case": "Pair programming",
        "pain_points": "Code review is slow",
        "key_features": "Inline suggestions",
        "source_quote": None,
        "user_story": None,
        "source_item_id": None,
        "source_item_title": None,
        "source_item_url": None,
        "reasoning": None,
        "overall_score": 8.5,
        "source_item_ids": [],
        "agent_trace": {},
        "created_at": datetime.now(timezone.utc),
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


@pytest.mark.asyncio
async def test_list_analysis_results_envelope():
    mock_results = [_make_mock_result()]
    mock_session = AsyncMock()
    count_res = MagicMock()
    count_res.scalar_one.return_value = 1
    res = MagicMock()
    res.scalars.return_value.all.return_value = mock_results
    mock_session.execute = AsyncMock(side_effect=[count_res, res])
    _override(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/analysis-results?page=1&per_page=20")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["total"] == 1


@pytest.mark.asyncio
async def test_list_analysis_results_min_score_out_of_range():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis-results?min_score=-1")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "400000"


@pytest.mark.asyncio
async def test_get_analysis_result_not_found():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        return_value=MagicMock(scalar_one_or_none=lambda: None)
    )
    _override(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/analysis-results/{uuid.uuid4()}")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "ANA001"


@pytest.mark.asyncio
async def test_get_analysis_result_invalid_uuid():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/analysis-results/not-a-uuid")
    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "ANA002"
