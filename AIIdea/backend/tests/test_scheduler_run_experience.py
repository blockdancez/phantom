"""scheduler._run_experience_impl 应：选 candidate → run_codex_experience →
parse_agent_report → 写 ProductExperienceReport 行。"""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.scheduler import jobs as jobs_module


class _FakeSession:
    def __init__(self, candidate=None):
        self.added: list = []
        self.committed = False
        self._candidate = candidate
        self._exhausted = False

    def add(self, obj):
        self.added.append(obj)

    async def get(self, model, key):
        return self._candidate

    async def execute(self, stmt):
        # 第一次返回 candidate；第二次（fallback path 不会触发）返回 None
        cur = self._candidate
        if self._exhausted:
            cur = None
        rv = SimpleNamespace(scalar_one_or_none=lambda c=cur: c)
        self._exhausted = True
        return rv

    async def commit(self):
        self.committed = True


class _Ctx:
    def __init__(self, sess):
        self._sess = sess

    async def __aenter__(self):
        return self._sess

    async def __aexit__(self, *a):
        return False


@pytest.fixture
def fake_factory(monkeypatch: pytest.MonkeyPatch):
    candidate = SimpleNamespace(
        id="cid1",
        slug="fake",
        name="FakeProduct",
        homepage_url="https://fake.test",
        last_experienced_at=None,
        experience_count=0,
    )
    sess = _FakeSession(candidate)
    monkeypatch.setattr(
        jobs_module,
        "get_async_session_factory",
        lambda: (lambda: _Ctx(sess)),
    )
    return sess


@pytest.mark.asyncio
async def test_run_experience_writes_row_via_codex_runner(
    fake_factory, monkeypatch: pytest.MonkeyPatch
):
    sample_md = (
        "# 产品体验报告\n\n## 概览\nFakeProduct 是测试产品。\n\n"
        "## 登录情况\ngoogle\n\n## 功能盘点\n- F: P | N\n\n"
        "## 优点\n好。\n\n## 缺点\n差。\n\n"
        "## 商业模式\n订阅。\n\n## 目标用户\n开发者。\n\n"
        "## 综合体验分\n7.5\n"
    )
    from src.product_experience.codex_runner import ExperienceRunResult

    async def fake_run(**kw):
        # 校验 scheduler 传给 codex_runner 的入参
        assert kw["slug"] == "fake"
        assert kw["name"] == "FakeProduct"
        assert kw["url"] == "https://fake.test"
        return ExperienceRunResult(
            markdown=sample_md,
            login_status="google",
            screenshots=[{"name": "landing", "path": "/x/landing.png", "taken_at": "t"}],
            trace={"returncode": 0},
        )

    import src.product_experience.codex_runner as cr
    monkeypatch.setattr(cr, "run_codex_experience", fake_run)

    await jobs_module._run_experience_impl()

    assert len(fake_factory.added) == 1
    row = fake_factory.added[0]
    assert row.product_slug == "fake"
    assert row.status == "completed"
    assert row.login_used == "google"
    assert row.overall_ux_score == 7.5
    assert row.summary_zh and "FakeProduct" in row.summary_zh


@pytest.mark.asyncio
async def test_run_experience_writes_failed_row_when_codex_returns_empty(
    fake_factory, monkeypatch: pytest.MonkeyPatch
):
    """codex 没产报告 (markdown="") → 仍写一行，但 status=completed 且 score 留空。

    注：当前实现不会把空 markdown 视为 failed —— failed 状态由 run_codex_experience
    自身在 trace 里标 reason，scheduler 拿到 ExperienceRunResult 仍走 happy 分支。
    这条用例锚定该行为，避免后续无意改动。
    """
    from src.product_experience.codex_runner import ExperienceRunResult

    async def fake_run(**kw):
        return ExperienceRunResult(
            markdown="",
            login_status="failed",
            screenshots=[],
            trace={"returncode": 1, "reason": "no_report_or_nonzero_exit"},
        )

    import src.product_experience.codex_runner as cr
    monkeypatch.setattr(cr, "run_codex_experience", fake_run)

    await jobs_module._run_experience_impl()

    assert len(fake_factory.added) == 1
    row = fake_factory.added[0]
    assert row.login_used == "failed"
    assert row.overall_ux_score is None
    assert row.summary_zh is None
