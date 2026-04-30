"""Tests for /api/stats/pipeline and /api/stats/sources."""

from __future__ import annotations

from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import OperationalError

from src.db import get_session
from src.main import app
from src.scheduler import runs


def _override(session):
    async def override():
        yield session

    app.dependency_overrides[get_session] = override


@pytest.mark.asyncio
async def test_stats_pipeline_reports_empty_when_no_data():
    runs.reset()
    mock_session = AsyncMock()
    # total_items count
    total = MagicMock()
    total.scalar_one.return_value = 0
    # processed stmt: returns tuple (processed, unprocessed, last_collected, distinct)
    processed_row = MagicMock()
    processed_row.one.return_value = (0, 0, None, 0)
    # analysis stmt: returns tuple (count, last_analysis)
    analysis_row = MagicMock()
    analysis_row.one.return_value = (0, None)
    mock_session.execute = AsyncMock(side_effect=[total, processed_row, analysis_row])
    _override(mock_session)
    app.state.scheduler = None

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats/pipeline")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    data = body["data"]
    assert data["total_items"] == 0
    assert data["scheduler_alive"] is False
    assert data["jobs"] == []


@pytest.mark.asyncio
async def test_stats_pipeline_includes_job_run_history():
    runs.reset()
    started = runs.record_start("collect_data")
    runs.record_finish("collect_data", started, status="success")

    mock_session = AsyncMock()
    total = MagicMock()
    total.scalar_one.return_value = 3
    processed_row = MagicMock()
    processed_row.one.return_value = (2, 1, datetime.now(timezone.utc), 1)
    analysis_row = MagicMock()
    analysis_row.one.return_value = (0, None)
    mock_session.execute = AsyncMock(side_effect=[total, processed_row, analysis_row])
    _override(mock_session)
    app.state.scheduler = None

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats/pipeline")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    jobs = resp.json()["data"]["jobs"]
    ids = {j["id"] for j in jobs}
    assert "collect_data" in ids
    row = next(j for j in jobs if j["id"] == "collect_data")
    assert row["last_status"] == "success"
    assert isinstance(row["last_duration_ms"], int)
    assert row["last_duration_ms"] >= 0
    runs.reset()


@pytest.mark.asyncio
async def test_stats_sources_empty():
    mock_session = AsyncMock()
    rows_res = MagicMock()
    rows_res.all.return_value = []
    total_res = MagicMock()
    total_res.scalar_one.return_value = 0
    recent_res = MagicMock()
    recent_res.scalar_one.return_value = 0
    mock_session.execute = AsyncMock(side_effect=[rows_res, total_res, recent_res])
    _override(mock_session)

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats/sources")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["total_items"] == 0
    assert body["data"]["items"] == []


@pytest.mark.asyncio
async def test_stats_sources_returns_503_when_db_unreachable():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=OperationalError("SELECT 1", {}, ConnectionError("no db"))
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats/sources")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "STATS001"
    assert body["message"] == "database not reachable"


@pytest.mark.asyncio
async def test_stats_pipeline_returns_503_when_db_unreachable():
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(
        side_effect=OperationalError("SELECT 1", {}, ConnectionError("no db"))
    )

    async def override():
        yield mock_session

    app.dependency_overrides[get_session] = override
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/stats/pipeline")
    finally:
        app.dependency_overrides.clear()

    assert resp.status_code == 503
    assert resp.json()["code"] == "STATS001"
