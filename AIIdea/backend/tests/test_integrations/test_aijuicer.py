"""单测 AIJuicer publisher: 阈值过滤 + initial_artifacts 注入 + 字段映射。

不连真实 scheduler/Redis；mock SchedulerClient.create_workflow。
SDK ≥0.7 起 idea 不再走 in-process agent，所以这里没有 consumer 测试。
"""
from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from src.integrations import aijuicer
from src.integrations.aijuicer import (
    _render_experience_markdown as render_experience_markdown,
    _render_idea_markdown as render_idea_markdown,
)


def test_render_idea_markdown_omits_screenshots():
    md = render_idea_markdown(
        {
            "idea_title": "AI 简历优化",
            "overall_score": 7.6,
            "product_idea": "P",
            "user_story": "U",
            "target_audience": "T",
            "use_case": "S",
            "pain_points": "PA",
            "key_features": "F",
            "source_quote": "Q",
            "reasoning": "R",
        }
    )
    assert "AI 简历优化" in md
    assert "综合评分:7.6" in md.replace("：", ":")
    assert "screenshots" not in md.lower()
    assert "## 用户故事" in md


def test_render_experience_markdown_omits_screenshots():
    md = render_experience_markdown(
        {
            "product_name": "FakeApp",
            "product_url": "https://fake.test",
            "overall_ux_score": 8.2,
            "summary_zh": "概览",
            "feature_inventory": [{"name": "F1", "where_found": "P", "notes": "N"}],
            "strengths": "+",
            "weaknesses": "-",
            "monetization_model": "M",
            "target_user": "T",
        }
    )
    assert "FakeApp 产品体验报告" in md
    assert "综合体验分:8.2" in md.replace("：", ":")
    assert "F1: P | N" in md
    assert "screenshot" not in md.lower()


def _patch_scheduler_client(monkeypatch) -> SimpleNamespace:
    fake = SimpleNamespace(
        create_workflow=AsyncMock(return_value={"id": "wf-1"}),
        close=AsyncMock(),
    )
    monkeypatch.setattr(
        "aijuicer_sdk.transport.SchedulerClient",
        lambda *a, **kw: fake,
    )
    return fake


@pytest.mark.asyncio
async def test_maybe_publish_idea_skips_when_disabled(monkeypatch):
    monkeypatch.delenv("AIJUICER_ENABLED", raising=False)
    fake = _patch_scheduler_client(monkeypatch)
    aijuicer.maybe_publish_idea({"idea_title": "x", "overall_score": 9, "source_id": "1"})
    fake.create_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_publish_idea_skips_below_threshold(monkeypatch):
    monkeypatch.setenv("AIJUICER_ENABLED", "1")
    monkeypatch.setenv("AIJUICER_SCORE_THRESHOLD", "7")
    fake = _patch_scheduler_client(monkeypatch)
    aijuicer.maybe_publish_idea(
        {"idea_title": "low", "overall_score": 6.5, "source_id": "1"}
    )
    await asyncio.sleep(0)
    fake.create_workflow.assert_not_called()


@pytest.mark.asyncio
async def test_maybe_publish_idea_passes_idea_md_as_initial_artifact(monkeypatch):
    """高分 idea → create_workflow 必带 initial_artifacts=[idea.md]。"""
    monkeypatch.setenv("AIJUICER_ENABLED", "1")
    monkeypatch.setenv("AIJUICER_SCORE_THRESHOLD", "7")
    fake = _patch_scheduler_client(monkeypatch)
    aijuicer.maybe_publish_idea(
        {
            "idea_title": "AI 简历优化",
            "overall_score": 8.2,
            "product_idea": "P",
            "source_id": "abc",
        }
    )
    for _ in range(5):
        await asyncio.sleep(0)

    fake.create_workflow.assert_awaited_once()
    kw = fake.create_workflow.await_args.kwargs
    assert kw["name"].startswith("AI Idea")
    assert kw["input"]["source_type"] == "idea"
    assert kw["input"]["source_id"] == "abc"
    # initial_artifacts 是 0.7 关键能力：idea.md 直接落盘，跳过 idea step
    artifacts = kw["initial_artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["step"] == "idea"
    assert artifacts[0]["key"] == "idea.md"
    assert "AI 简历优化" in artifacts[0]["content"]
    assert artifacts[0]["content_type"] == "text/markdown"


@pytest.mark.asyncio
async def test_maybe_publish_experience_passes_url_and_initial_artifact(monkeypatch):
    monkeypatch.setenv("AIJUICER_ENABLED", "1")
    monkeypatch.setenv("AIJUICER_SCORE_THRESHOLD", "7")
    fake = _patch_scheduler_client(monkeypatch)
    aijuicer.maybe_publish_experience(
        {
            "product_name": "X",
            "product_url": "https://x.test",
            "overall_ux_score": 8.5,
            "summary_zh": "S",
            "source_id": "rid",
        }
    )
    for _ in range(5):
        await asyncio.sleep(0)

    fake.create_workflow.assert_awaited_once()
    kw = fake.create_workflow.await_args.kwargs
    assert kw["input"]["source_type"] == "experience"
    assert kw["input"]["product_url"] == "https://x.test"
    artifacts = kw["initial_artifacts"]
    assert len(artifacts) == 1
    assert artifacts[0]["step"] == "idea"
    assert artifacts[0]["key"] == "idea.md"
    assert "X 产品体验报告" in artifacts[0]["content"]
