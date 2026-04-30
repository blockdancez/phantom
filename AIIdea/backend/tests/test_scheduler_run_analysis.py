"""Tests for scheduler.jobs._run_analysis_impl's required-field guard (feature-4).

The code-reviewer flagged that the scheduled-path used to write a zeroed
``AnalysisResult`` even when ``idea_title`` / ``overall_score`` were
missing, contradicting plan spec ("不入库，记 error 日志").
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.scheduler import jobs as jobs_module


class _FakeSession:
    def __init__(self):
        self.added = []
        self.committed = False

    def add(self, obj):
        self.added.append(obj)

    async def commit(self):
        self.committed = True

    async def execute(self, _stmt):
        # _resolve_unique_project_name + duplicate-anchor guard query via
        # ``await session.execute(...)``. The stub returns "no row" so
        # those guards pass-through to the happy path.
        from types import SimpleNamespace
        return SimpleNamespace(scalar_one_or_none=lambda: None)


class _FakeCtxManager:
    def __init__(self, session):
        self.session = session

    async def __aenter__(self):
        return self.session

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def fake_session(monkeypatch: pytest.MonkeyPatch):
    s = _FakeSession()
    monkeypatch.setattr(
        jobs_module,
        "get_async_session_factory",
        lambda: (lambda: _FakeCtxManager(s)),
    )
    return s


def _raw_report(body: str = "valid markdown report more than 80 characters of substance"):
    padded = body + (" x" * 40)
    assert len(padded) > 80
    return padded


@pytest.mark.asyncio
async def test_run_analysis_skips_when_idea_title_missing(
    fake_session, monkeypatch: pytest.MonkeyPatch
):
    async def _agent(session):
        return {
            "analysis": _raw_report(),
            "trace": [],
            "message_count": 1,
        }

    async def _extract(raw):
        return SimpleNamespace(
            idea_title="",  # missing
            product_idea="p",
            target_audience="ta",
            use_case="uc",
            pain_points="pp",
            key_features="kf",
            source_quote="q",
            user_story="us",
            source_item_id=None,
            reasoning="r",
            overall_score=7.0,
            is_digital_product=True,
            digital_product_form="web",
            project_name='proj-test',
        )

    monkeypatch.setattr(jobs_module, "run_analysis_agent", _agent)

    async def _wrap(raw):
        return await _extract(raw)

    await jobs_module._run_analysis_impl(_wrap)

    assert fake_session.added == []
    assert fake_session.committed is False


@pytest.mark.asyncio
async def test_run_analysis_skips_when_overall_score_missing(
    fake_session, monkeypatch: pytest.MonkeyPatch
):
    async def _agent(session):
        return {"analysis": _raw_report(), "trace": [], "message_count": 1}

    async def _extract(raw):
        return SimpleNamespace(
            idea_title="ok",
            product_idea="p",
            target_audience="ta",
            use_case="uc",
            pain_points="pp",
            key_features="kf",
            source_quote="q",
            user_story="us",
            source_item_id=None,
            reasoning="r",
            overall_score=None,  # missing
            is_digital_product=True,
            digital_product_form="web",
            project_name='proj-test',
        )

    monkeypatch.setattr(jobs_module, "run_analysis_agent", _agent)
    await jobs_module._run_analysis_impl(_extract)
    assert fake_session.added == []


@pytest.mark.asyncio
async def test_run_analysis_skips_on_extraction_failure(
    fake_session, monkeypatch: pytest.MonkeyPatch
):
    async def _agent(session):
        return {"analysis": _raw_report(), "trace": [], "message_count": 1}

    async def _extract(raw):
        raise RuntimeError("llm unavailable")

    monkeypatch.setattr(jobs_module, "run_analysis_agent", _agent)
    await jobs_module._run_analysis_impl(_extract)
    assert fake_session.added == []


@pytest.mark.asyncio
async def test_run_analysis_writes_on_happy_path(
    fake_session, monkeypatch: pytest.MonkeyPatch
):
    async def _agent(session):
        return {"analysis": _raw_report(), "trace": [], "message_count": 3}

    async def _extract(raw):
        return SimpleNamespace(
            idea_title="买菜助手",
            product_idea="p",
            target_audience="ta",
            use_case="uc",
            pain_points="pp",
            key_features="kf",
            source_quote="q",
            user_story="us",
            source_item_id=None,
            reasoning="r",
            overall_score=8.2,
            is_digital_product=True,
            digital_product_form="mobile_app",
            project_name='proj-test',
        )

    monkeypatch.setattr(jobs_module, "run_analysis_agent", _agent)
    await jobs_module._run_analysis_impl(_extract)
    assert len(fake_session.added) == 1
    record = fake_session.added[0]
    assert record.idea_title == "买菜助手"
    assert record.overall_score == pytest.approx(8.2)


@pytest.mark.asyncio
async def test_run_analysis_skips_on_bad_score_string(
    fake_session, monkeypatch: pytest.MonkeyPatch
):
    async def _agent(session):
        return {"analysis": _raw_report(), "trace": [], "message_count": 1}

    async def _extract(raw):
        return SimpleNamespace(
            idea_title="ok",
            product_idea="p",
            target_audience="ta",
            use_case="uc",
            pain_points="pp",
            key_features="kf",
            source_quote="q",
            user_story="us",
            source_item_id=None,
            reasoning="r",
            overall_score="not-a-number",
            is_digital_product=True,
            digital_product_form="web",
            project_name='proj-test',
        )

    monkeypatch.setattr(jobs_module, "run_analysis_agent", _agent)
    await jobs_module._run_analysis_impl(_extract)
    assert fake_session.added == []


def test_parse_source_item_uuid_accepts_valid():
    import uuid as _uuid

    real = str(_uuid.uuid4())
    assert str(jobs_module._parse_source_item_uuid(real)) == real


def test_parse_source_item_uuid_rejects_garbage():
    assert jobs_module._parse_source_item_uuid(None) is None
    assert jobs_module._parse_source_item_uuid("") is None
    assert jobs_module._parse_source_item_uuid("not-a-uuid") is None


@pytest.mark.asyncio
async def test_run_analysis_skips_when_idea_not_digital_product(
    fake_session, monkeypatch: pytest.MonkeyPatch
):
    """Physical goods / offline services / pure life-hack tips must be dropped:
    the analysis table is meant for internet/AI/SaaS product ideas only."""

    async def _agent(session):
        return {"analysis": _raw_report(), "trace": [], "message_count": 1}

    async def _extract(raw):
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

    monkeypatch.setattr(jobs_module, "run_analysis_agent", _agent)
    await jobs_module._run_analysis_impl(_extract)
    assert fake_session.added == []
    assert fake_session.committed is False
