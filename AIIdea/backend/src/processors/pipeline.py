"""Processing pipeline — Enrich → Analyze → Persist.

Orchestrates the two processing steps for each unprocessed SourceItem:

1. :class:`Enricher` fetches the real article text from the source URL and
   overwrites ``item.content`` when the new body is longer than what we had.
2. :class:`Analyzer` makes a single structured LLM call and returns a full
   insight bundle (category, tags, summary_zh, problem, opportunity,
   target_user, why_now, hotness, novelty, score).

Errors on any individual item are logged and skipped — one bad item never
kills the batch.

Per-item work runs concurrently (asyncio.gather + Semaphore) since both
steps are pure IO (HTTP / OpenAI). Concurrency is bounded so OpenAI rate
limits and remote sites don't get hammered. ORM attribute writes are
in-memory only — session.commit() is called once on the main coroutine,
which is the SQLAlchemy concurrency contract.
"""

from __future__ import annotations

import asyncio

import structlog
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.models.source_item import SourceItem
from src.processors.analyzer import Analyzer
from src.processors.enricher import Enricher

logger = structlog.get_logger()


_DEFAULT_CONCURRENCY = 10


async def run_processing_pipeline(
    session: AsyncSession,
    batch_size: int = 100,
    concurrency: int = _DEFAULT_CONCURRENCY,
) -> int:
    """Process up to ``batch_size`` unprocessed SourceItem rows concurrently.

    Returns the count of rows flipped to ``processed=True`` (success +
    invalid-category fallback). Items that throw stay ``processed=False``
    so the next run retries them.
    """
    logger.info(
        "处理管线开始",
        batch_size=batch_size,
        concurrency=concurrency,
    )

    stmt = (
        select(SourceItem)
        .where(SourceItem.processed.is_(False))
        .order_by(SourceItem.collected_at.desc())
        .limit(batch_size)
    )
    items = (await session.execute(stmt)).scalars().all()

    if not items:
        logger.info("处理管线跳过", reason="no_unprocessed_items")
        return 0

    enricher = Enricher()
    analyzer = Analyzer()
    semaphore = asyncio.Semaphore(concurrency)

    async def _process_one(item: SourceItem) -> bool:
        async with semaphore:
            try:
                enriched = await enricher.enrich(item)
                if enriched and len(enriched) > len(item.content or ""):
                    item.content = enriched

                try:
                    analysis = await analyzer.analyze(item)
                except ValidationError as exc:
                    # Feature-3 error matrix: off-taxonomy label → write with
                    # category="unknown" instead of leaving the row pending.
                    logger.warning(
                        "条目非法分类",
                        item_id=str(item.id),
                        error=str(exc)[:200],
                    )
                    item.category = "unknown"
                    item.tags = ["unknown"]
                    item.score = 0.0
                    item.summary_zh = None
                    item.problem = None
                    item.opportunity = None
                    item.target_user = None
                    item.why_now = None
                    item.signal_type = "unknown"
                    item.processed = True
                    return True

                item.category = analysis.category
                item.tags = list(analysis.tags)
                item.score = float(analysis.score)
                item.summary_zh = analysis.summary_zh
                item.problem = analysis.problem
                item.opportunity = analysis.opportunity
                item.target_user = analysis.target_user
                item.why_now = analysis.why_now
                item.signal_type = analysis.signal_type
                item.processed = True

                logger.debug(
                    "条目已处理",
                    item_id=str(item.id),
                    source=item.source,
                    category=item.category,
                    score=item.score,
                )
                return True
            except Exception:
                # Per feature-3: LLM/network failure → keep processed=False,
                # log, don't propagate. The next scheduler run retries.
                logger.exception("条目处理失败", item_id=str(item.id))
                return False

    try:
        results = await asyncio.gather(*(_process_one(it) for it in items))
    finally:
        await enricher.close()

    processed_count = sum(1 for ok in results if ok)
    await session.commit()
    logger.info(
        "处理管线结束",
        processed=processed_count,
        seen=len(items),
    )
    return processed_count
