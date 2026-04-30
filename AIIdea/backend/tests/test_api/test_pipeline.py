"""Tests for feature-1 / feature-2: pipeline trigger + unified response."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import pipeline as pipeline_module
from src.collectors.base import BaseCollector
from src.main import app


class _FakeJob:
    def __init__(self, job_id: str):
        self.id = job_id
        self.name = job_id
        self.next_run_time = None

    def modify(self, **kwargs):
        self.next_run_time = kwargs.get("next_run_time")


class _FakeScheduler:
    def __init__(self, ids):
        self._jobs = {i: _FakeJob(i) for i in ids}
        self.running = True

    def get_job(self, job_id):
        return self._jobs.get(job_id)

    def get_jobs(self):
        return list(self._jobs.values())


class _FakeCollector(BaseCollector):
    name = "fake"

    def __init__(self, items=None, *, raises: Exception | None = None):
        # Skip BaseCollector.__init__ (which opens an httpx client) in tests.
        self._items = items or []
        self._raises = raises
        self.closed = False

    async def collect(self, limit: int = 30) -> list[dict]:
        if self._raises:
            raise self._raises
        return self._items

    async def close(self) -> None:
        self.closed = True


@pytest.fixture
def scheduler_with_jobs():
    sched = _FakeScheduler(["collect_data", "process_data", "analyze_data"])
    app.state.scheduler = sched
    yield sched
    app.state.scheduler = None


@pytest.fixture
def no_scheduler():
    app.state.scheduler = None
    yield


@pytest.mark.asyncio
async def test_trigger_unknown_job_returns_pipeline001(scheduler_with_jobs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/unknown_job")
    assert resp.status_code == 404
    body = resp.json()
    assert body["code"] == "PIPELINE001"
    # Message must be byte-identical to the plan contract — reviewer
    # flagged free-form phrasings as an unstable client contract.
    assert body["message"] == "unknown job_id"


@pytest.mark.asyncio
async def test_trigger_scheduled_job_happy_path(scheduler_with_jobs):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/collect_data")
    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["job_id"] == "collect_data"
    assert body["data"]["status"] == "triggered"


@pytest.mark.asyncio
async def test_trigger_when_scheduler_down_returns_503(no_scheduler):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/collect_data")
    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "PIPELINE003"


@pytest.mark.asyncio
async def test_trigger_per_source_runs_collector_and_reports_inserted(
    scheduler_with_jobs, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeCollector(
        items=[
            {"source": "hackernews", "title": "t", "url": "https://x/1", "raw_data": {}},
        ],
    )

    # Swap the HackerNews factory with our fake.
    monkeypatch.setitem(
        pipeline_module._PER_SOURCE_COLLECTORS,
        "collect_hackernews",
        lambda: fake,
    )

    # Patch ingest_items to avoid needing a real DB session.
    async def _fake_ingest(session, items):
        return len(items)

    class _Ctx:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    def _factory():
        return lambda: _Ctx()

    monkeypatch.setattr(pipeline_module, "get_async_session_factory", _factory)
    monkeypatch.setattr(pipeline_module, "ingest_items", _fake_ingest)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/collect_hackernews")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["inserted"] == 1
    assert body["data"]["source"] == "hackernews"
    assert fake.closed is True


@pytest.mark.asyncio
async def test_trigger_per_source_empty_returns_inserted_zero(
    scheduler_with_jobs, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeCollector(items=[])
    monkeypatch.setitem(
        pipeline_module._PER_SOURCE_COLLECTORS,
        "collect_reddit",
        lambda: fake,
    )

    async def _fake_ingest(session, items):
        return 0

    class _Ctx:
        async def __aenter__(self):
            return AsyncMock()

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        pipeline_module, "get_async_session_factory", lambda: (lambda: _Ctx())
    )
    monkeypatch.setattr(pipeline_module, "ingest_items", _fake_ingest)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/collect_reddit")

    assert resp.status_code == 200
    assert resp.json()["data"]["inserted"] == 0


@pytest.mark.asyncio
async def test_trigger_per_source_collector_failure_returns_503(
    scheduler_with_jobs, monkeypatch: pytest.MonkeyPatch
):
    fake = _FakeCollector(raises=RuntimeError("boom"))
    monkeypatch.setitem(
        pipeline_module._PER_SOURCE_COLLECTORS,
        "collect_producthunt",
        lambda: fake,
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/collect_producthunt")

    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "503000"
    assert fake.closed is True


@pytest.mark.asyncio
async def test_trigger_per_source_concurrent_returns_pipeline002(
    scheduler_with_jobs, monkeypatch: pytest.MonkeyPatch
):
    # Simulate the lock already held to emulate a second caller hitting the
    # endpoint while the first is still running.
    monkeypatch.setitem(
        pipeline_module._PER_SOURCE_COLLECTORS,
        "collect_github_trending",
        lambda: _FakeCollector(items=[]),
    )
    pipeline_module._running_per_source.add("collect_github_trending")

    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/pipeline/trigger/collect_github_trending")
    finally:
        pipeline_module._running_per_source.discard("collect_github_trending")

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "PIPELINE002"
    assert body["message"] == "job already running"


@pytest.mark.asyncio
async def test_trigger_scheduled_already_running_returns_pipeline002(scheduler_with_jobs):
    """Second trigger of a registered cron job while the first is still
    running must return PIPELINE002, not silently accept a duplicate."""
    pipeline_module._running_scheduled.add("process_data")
    try:
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post("/api/pipeline/trigger/process_data")
    finally:
        pipeline_module._running_scheduled.discard("process_data")

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "PIPELINE002"
    assert body["message"] == "job already running"


def test_list_triggerable_ids_includes_all_collectors_and_cron():
    ids = set(pipeline_module.list_triggerable_ids())
    assert {"collect_data", "process_data", "analyze_data"} <= ids
    assert {
        "collect_hackernews",
        "collect_reddit",
        "collect_producthunt",
        "collect_github_trending",
        "collect_twitter",
        "collect_rss",
    } <= ids
