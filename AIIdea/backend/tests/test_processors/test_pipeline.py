"""Unit tests for the processing pipeline (feature-3).

Covers happy path, empty batch, LLM failure recovery, and batch-size
configurability. All LLM + HTTP calls are mocked.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.processors import pipeline as pipeline_module
from src.processors.analyzer import ItemAnalysis


def _fake_item(**overrides):
    defaults = {
        "id": uuid.uuid4(),
        "source": "hackernews",
        "title": "t",
        "url": "https://example.com/1",
        "content": "short body",
        "raw_data": {},
        "category": None,
        "tags": None,
        "score": None,
        "summary_zh": None,
        "problem": None,
        "opportunity": None,
        "target_user": None,
        "why_now": None,
        "processed": False,
        "collected_at": datetime.now(timezone.utc),
        "created_at": datetime.now(timezone.utc),
    }
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def _mock_session_with(items):
    session = AsyncMock()
    result = MagicMock()
    result.scalars.return_value.all.return_value = items
    session.execute = AsyncMock(return_value=result)
    session.commit = AsyncMock()
    return session


@pytest.mark.asyncio
async def test_run_processing_pipeline_empty_returns_zero():
    session = _mock_session_with([])
    count = await pipeline_module.run_processing_pipeline(session, batch_size=50)
    assert count == 0


@pytest.mark.asyncio
async def test_run_processing_pipeline_happy_path():
    item = _fake_item()
    session = _mock_session_with([item])

    analysis = ItemAnalysis(
        category="AI/ML",
        tags=["ai"],
        summary_zh="摘要",
        problem="P",
        opportunity="O",
        target_user="U",
        why_now="N",
        hotness=7.0,
        novelty=8.0,
        score=7.4,
        signal_type='pain_point',
            )

    with (
        patch("src.processors.pipeline.Enricher") as enricher_cls,
        patch("src.processors.pipeline.Analyzer") as analyzer_cls,
    ):
        enricher = enricher_cls.return_value
        enricher.enrich = AsyncMock(return_value="")
        enricher.close = AsyncMock()
        analyzer = analyzer_cls.return_value
        analyzer.analyze = AsyncMock(return_value=analysis)

        processed = await pipeline_module.run_processing_pipeline(
            session, batch_size=10
        )

    assert processed == 1
    assert item.category == "AI/ML"
    assert item.tags == ["ai"]
    assert item.score == pytest.approx(7.4)
    assert item.processed is True


@pytest.mark.asyncio
async def test_run_processing_pipeline_enricher_replaces_shorter_content():
    item = _fake_item(content="short")
    session = _mock_session_with([item])
    analysis = ItemAnalysis(
        category="Other",
        tags=["unknown"],
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

    with (
        patch("src.processors.pipeline.Enricher") as enricher_cls,
        patch("src.processors.pipeline.Analyzer") as analyzer_cls,
    ):
        enricher_cls.return_value.enrich = AsyncMock(
            return_value="this is a much longer article body than what we had"
        )
        enricher_cls.return_value.close = AsyncMock()
        analyzer_cls.return_value.analyze = AsyncMock(return_value=analysis)

        await pipeline_module.run_processing_pipeline(session, batch_size=10)

    assert "much longer article body" in item.content


@pytest.mark.asyncio
async def test_run_processing_pipeline_single_item_failure_does_not_kill_batch():
    ok = _fake_item(id=uuid.uuid4())
    bad = _fake_item(id=uuid.uuid4())
    session = _mock_session_with([bad, ok])
    good_analysis = ItemAnalysis(
        category="Productivity",
        tags=["x"],
        summary_zh="s",
        problem="p",
        opportunity="o",
        target_user="u",
        why_now="n",
        hotness=3.0,
        novelty=3.0,
        score=3.0,
        signal_type='pain_point',
            )

    call_count = {"n": 0}

    async def flaky(item):
        call_count["n"] += 1
        if item is bad:
            raise RuntimeError("llm crashed")
        return good_analysis

    with (
        patch("src.processors.pipeline.Enricher") as enricher_cls,
        patch("src.processors.pipeline.Analyzer") as analyzer_cls,
    ):
        enricher_cls.return_value.enrich = AsyncMock(return_value="")
        enricher_cls.return_value.close = AsyncMock()
        analyzer_cls.return_value.analyze = AsyncMock(side_effect=flaky)

        processed = await pipeline_module.run_processing_pipeline(
            session, batch_size=10
        )

    assert processed == 1
    assert ok.processed is True
    assert bad.processed is False


@pytest.mark.asyncio
async def test_run_processing_pipeline_respects_batch_size_default():
    # Default batch size was raised to 100 (paired with concurrent fan-out)
    # so a single scheduler tick can absorb a meaningful amount of backlog.
    import inspect

    sig = inspect.signature(pipeline_module.run_processing_pipeline)
    assert sig.parameters["batch_size"].default == 100
    assert sig.parameters["concurrency"].default == 10


@pytest.mark.asyncio
async def test_run_processing_pipeline_llm_failure_keeps_processed_false():
    """Feature-3 contract: a raw LLM failure (network, OpenAI 500 etc.) must
    leave the item ``processed=False`` so it gets retried in the next batch.
    """
    bad = _fake_item()
    session = _mock_session_with([bad])

    with (
        patch("src.processors.pipeline.Enricher") as enricher_cls,
        patch("src.processors.pipeline.Analyzer") as analyzer_cls,
    ):
        enricher_cls.return_value.enrich = AsyncMock(return_value="")
        enricher_cls.return_value.close = AsyncMock()
        analyzer_cls.return_value.analyze = AsyncMock(
            side_effect=RuntimeError("openai 500")
        )

        processed = await pipeline_module.run_processing_pipeline(
            session, batch_size=10
        )

    assert processed == 0
    assert bad.processed is False


@pytest.mark.asyncio
async def test_run_processing_pipeline_validation_error_writes_unknown():
    """Feature-3 contract: an off-taxonomy category (ValidationError) lands
    ``category='unknown'`` with ``processed=True`` so stats still count it.
    """
    from pydantic import ValidationError

    from src.processors.analyzer import ItemAnalysis

    item = _fake_item()
    session = _mock_session_with([item])

    # Build a real ValidationError.
    try:
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
        validation_error: ValidationError | None = None
    except ValidationError as real_err:
        validation_error = real_err
    assert validation_error is not None

    with (
        patch("src.processors.pipeline.Enricher") as enricher_cls,
        patch("src.processors.pipeline.Analyzer") as analyzer_cls,
    ):
        enricher_cls.return_value.enrich = AsyncMock(return_value="")
        enricher_cls.return_value.close = AsyncMock()
        analyzer_cls.return_value.analyze = AsyncMock(side_effect=validation_error)

        processed = await pipeline_module.run_processing_pipeline(
            session, batch_size=10
        )

    assert processed == 1
    assert item.processed is True
    assert item.category == "unknown"
    assert item.tags == ["unknown"]
    assert item.score == 0.0
