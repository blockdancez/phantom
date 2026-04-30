"""Unit tests for Analyzer behavior (feature-3)."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest
from pydantic import ValidationError

from src.processors.analyzer import Analyzer, ItemAnalysis


def _fake_item():
    m = MagicMock()
    m.id = uuid.uuid4()
    m.title = "Title"
    m.source = "hackernews"
    m.content = "body text"
    m.raw_data = {"score": 10}
    m.collected_at = datetime.now(timezone.utc)
    return m


@pytest.mark.asyncio
async def test_analyzer_returns_llm_result_on_success():
    a = Analyzer.__new__(Analyzer)
    a.model_name = "gpt-4o-mini"
    expected = ItemAnalysis(
        category="AI/ML",
        tags=["ai"],
        summary_zh="s",
        problem="p",
        opportunity="o",
        target_user="u",
        why_now="n",
        hotness=5.0,
        novelty=5.0,
        score=5.0,
        signal_type='pain_point',
            )
    a.llm = MagicMock()
    a.llm.ainvoke = AsyncMock(return_value=expected)

    result = await a.analyze(_fake_item())
    assert result is expected


@pytest.mark.asyncio
async def test_analyzer_propagates_llm_failure():
    """Per feature-3: LLM failure must propagate so the outer pipeline can
    leave ``processed=False`` and retry next batch. Swallowing the
    exception here would cause the row to be written as processed with
    zeroed-out fields, which the code-reviewer flagged as incorrect."""
    a = Analyzer.__new__(Analyzer)
    a.model_name = "gpt-4o-mini"
    a.llm = MagicMock()
    a.llm.ainvoke = AsyncMock(side_effect=RuntimeError("openai 500"))

    with pytest.raises(RuntimeError, match="openai 500"):
        await a.analyze(_fake_item())


@pytest.mark.asyncio
async def test_analyzer_propagates_validation_error():
    """A pydantic ValidationError (off-taxonomy category) must propagate so
    the orchestrator can apply its ``category='unknown'`` fallback."""
    a = Analyzer.__new__(Analyzer)
    a.model_name = "gpt-4o-mini"
    a.llm = MagicMock()

    # Build a real ValidationError instance by invoking ItemAnalysis with
    # a literal-incompatible category, which is exactly what LangChain would
    # raise if the model returned an off-schema label.
    def _raise_validation():
        ItemAnalysis(
            category="NotACategory",  # type: ignore[arg-type]
            tags=["x"],
            summary_zh="s",
            problem="p",
            opportunity="o",
            target_user="u",
            why_now="n",
            hotness=0.0,
            novelty=0.0,
            score=0.0,
            signal_type='pain_point',
                )

    try:
        _raise_validation()
    except ValidationError as real_err:
        a.llm.ainvoke = AsyncMock(side_effect=real_err)

    with pytest.raises(ValidationError):
        await a.analyze(_fake_item())


def test_unknown_is_a_valid_category():
    model = ItemAnalysis(
        category="unknown",
        tags=["x"],
        summary_zh="s",
        problem="p",
        opportunity="o",
        target_user="u",
        why_now="n",
        hotness=0.0,
        novelty=0.0,
        score=0.0,
        signal_type='pain_point',
            )
    assert model.category == "unknown"
