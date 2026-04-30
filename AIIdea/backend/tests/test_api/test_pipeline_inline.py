"""Tests for inline process + analyze trigger endpoints (feature-3 / feature-4)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from httpx import ASGITransport, AsyncClient

from src.api import pipeline as pipeline_module
from src.main import app


@pytest.fixture(autouse=True)
def _clear_locks():
    pipeline_module._running_scheduled.clear()
    pipeline_module._running_per_source.clear()
    yield
    pipeline_module._running_scheduled.clear()
    pipeline_module._running_per_source.clear()


@pytest.mark.asyncio
async def test_trigger_process_returns_processed_count(monkeypatch: pytest.MonkeyPatch):
    async def _fake_run(batch_size=50):
        assert batch_size == 50
        return 3

    monkeypatch.setattr(pipeline_module, "_run_inline_process", _fake_run)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/process")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["processed"] == 3
    assert body["data"]["status"] == "completed"
    assert body["data"]["job_id"] == "process"
    assert isinstance(body["data"]["duration_ms"], int)


@pytest.mark.asyncio
async def test_trigger_process_empty_returns_zero(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(
        pipeline_module, "_run_inline_process", AsyncMock(return_value=0)
    )

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/process")

    assert resp.status_code == 200
    assert resp.json()["data"]["processed"] == 0


@pytest.mark.asyncio
async def test_trigger_process_failure_returns_503(monkeypatch: pytest.MonkeyPatch):
    async def _boom(batch_size=50):
        raise RuntimeError("db gone")

    monkeypatch.setattr(pipeline_module, "_run_inline_process", _boom)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/process")

    assert resp.status_code == 503
    body = resp.json()
    assert body["code"] == "503000"


@pytest.mark.asyncio
async def test_trigger_process_concurrent_returns_pipeline002():
    # Use the public helper so inline (``process``) and scheduled
    # (``process_data``) share one running key.
    pipeline_module.mark_scheduled_running("process")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/process")

    assert resp.status_code == 400
    body = resp.json()
    assert body["code"] == "PIPELINE002"
    assert body["message"] == "job already running"


@pytest.mark.asyncio
async def test_trigger_process_blocked_by_scheduled_process_data_running():
    """Cross-path concurrency: scheduled ``process_data`` in flight must
    block inline ``process`` via the shared running key."""
    pipeline_module.mark_scheduled_running("process_data")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/process")

    assert resp.status_code == 400
    assert resp.json()["code"] == "PIPELINE002"


@pytest.mark.asyncio
async def test_trigger_analyze_blocked_by_scheduled_analyze_data_running():
    pipeline_module.mark_scheduled_running("analyze_data")

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/analyze")

    assert resp.status_code == 400
    assert resp.json()["code"] == "PIPELINE002"


@pytest.mark.asyncio
async def test_trigger_analyze_returns_generated_count(monkeypatch: pytest.MonkeyPatch):
    async def _fake_run():
        return 1, "written"

    monkeypatch.setattr(pipeline_module, "_run_inline_analyze_once", _fake_run)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/analyze")

    assert resp.status_code == 200
    body = resp.json()
    assert body["code"] == "000000"
    assert body["data"]["generated"] == 1
    assert body["data"]["detail"] == "written"
    assert body["data"]["job_id"] == "analyze"


@pytest.mark.asyncio
async def test_trigger_analyze_timeout_still_succeeds(monkeypatch: pytest.MonkeyPatch):
    # _run_inline_analyze_once itself persists a timeout row and returns (0, "timeout")
    async def _fake_run():
        return 0, "timeout"

    monkeypatch.setattr(pipeline_module, "_run_inline_analyze_once", _fake_run)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/pipeline/trigger/analyze")

    assert resp.status_code == 200
    body = resp.json()
    assert body["data"]["generated"] == 0
    assert body["data"]["detail"] == "timeout"


def test_list_triggerable_ids_includes_process_and_analyze():
    ids = set(pipeline_module.list_triggerable_ids())
    assert "process" in ids
    assert "analyze" in ids


# ---- _run_inline_analyze_once unit coverage ----


class _FakeCtxSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def execute(self, _stmt):
        from types import SimpleNamespace
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _FakeCtxManager:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def fake_session_factory(monkeypatch: pytest.MonkeyPatch):
    session = _FakeCtxSession()
    monkeypatch.setattr(
        pipeline_module,
        "get_async_session_factory",
        lambda: (lambda: _FakeCtxManager(session)),
    )
    return session


@pytest.mark.asyncio
async def test_run_inline_analyze_once_timeout_writes_partial(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    async def _blow_up(session):
        raise asyncio.TimeoutError

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _blow_up)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 0
    assert detail == "timeout"
    assert fake_session_factory.committed is True
    assert len(fake_session_factory.added) == 1
    record = fake_session_factory.added[0]
    assert record.overall_score == 0.0
    assert record.agent_trace["last_step"] == "timeout"


@pytest.mark.asyncio
async def test_run_inline_analyze_once_exception_writes_partial(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    async def _blow_up(session):
        raise RuntimeError("graph crash")

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _blow_up)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 0
    assert detail == "failed"
    assert fake_session_factory.added[0].agent_trace["last_step"] == "failed"


@pytest.mark.asyncio
async def test_run_inline_analyze_once_skips_on_empty_report(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    async def _fake_agent(session):
        return "", [], 0

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _fake_agent)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 0
    assert detail == "skipped_empty"
    assert fake_session_factory.added == []


@pytest.mark.asyncio
async def test_run_inline_analyze_once_skips_on_bail_marker(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    async def _fake_agent(session):
        return (
            "A long enough message that contains the bail marker "
            "NO_VIABLE_IDEA_FOUND somewhere in the middle of the text.",
            [],
            3,
        )

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _fake_agent)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 0
    assert detail == "skipped_bail"


@pytest.mark.asyncio
async def test_run_inline_analyze_once_skips_on_no_lineage(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    long_report = "valid markdown report that is definitely longer than 80 characters for the guard."
    assert len(long_report) > 80

    async def _fake_agent(session):
        return long_report, [], 3

    async def _fake_extract(raw):
        return SimpleNamespace(
            idea_title="t",
            product_idea="p",
            target_audience="ta",
            use_case="uc",
            pain_points="pp",
            key_features="kf",
            source_quote=None,
            user_story=None,
            source_item_id=None,
            reasoning=None,
            overall_score=7.0,
            is_digital_product=True,
            digital_product_form="web",
            project_name='proj-test',
        )

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _fake_agent)
    import src.agent.extractor as extractor_mod

    monkeypatch.setattr(extractor_mod, "extract_agent_report", _fake_extract)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 0
    assert detail == "skipped_no_lineage"


@pytest.mark.asyncio
async def test_run_inline_analyze_once_skips_when_idea_not_digital_product(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    long_report = "valid markdown report that is definitely longer than 80 characters for the guard."

    async def _fake_agent(session):
        return long_report, [], 3

    async def _fake_extract(raw):
        return SimpleNamespace(
            idea_title="防松鼠快递包裹保护袋",
            product_idea="一种耐咬的快递包装袋",
            target_audience="网购用户",
            use_case="收快递时",
            pain_points="松鼠咬破包裹",
            key_features="缝制耐咬层",
            source_quote="a squirrel ate through the envelope",
            user_story="story",
            source_item_id=None,
            reasoning="r",
            overall_score=7.0,
            is_digital_product=False,
            digital_product_form=None,
            project_name='proj-test',
        )

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _fake_agent)
    import src.agent.extractor as extractor_mod

    monkeypatch.setattr(extractor_mod, "extract_agent_report", _fake_extract)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 0
    assert detail == "skipped_non_digital_product"
    assert fake_session_factory.added == []


@pytest.mark.asyncio
async def test_run_inline_analyze_once_writes_on_happy_path(
    monkeypatch: pytest.MonkeyPatch, fake_session_factory
):
    long_report = "valid markdown report that is definitely longer than 80 characters for the guard."

    async def _fake_agent(session):
        return long_report, [{"role": "user", "content": "hi"}], 5

    async def _fake_extract(raw):
        return SimpleNamespace(
            idea_title="买菜助手",
            product_idea="p",
            target_audience="ta",
            use_case="uc",
            pain_points="pp",
            key_features="kf",
            source_quote="quote",
            user_story="story",
            source_item_id=None,
            reasoning="r",
            overall_score=8.4,
            is_digital_product=True,
            digital_product_form="mobile_app",
            project_name='proj-test',
        )

    monkeypatch.setattr(pipeline_module, "_run_agent_with_timeout", _fake_agent)
    import src.agent.extractor as extractor_mod

    monkeypatch.setattr(extractor_mod, "extract_agent_report", _fake_extract)

    generated, detail = await pipeline_module._run_inline_analyze_once()
    assert generated == 1
    assert detail == "written"
    assert fake_session_factory.added[0].idea_title == "买菜助手"
    assert fake_session_factory.added[0].overall_score == pytest.approx(8.4)
