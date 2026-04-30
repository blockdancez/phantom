"""Re-parse AnalysisResult rows that don't have the new product fields yet,
using either the raw agent report stored in ``agent_trace.raw_report`` (new
schema) or the legacy ``idea_description`` (old schema) as the source text.

Usage:
    DATABASE_URL=... OPENAI_API_KEY=... PYTHONPATH=. \\
        python scripts/backfill_analysis_reports.py
"""

from __future__ import annotations

import asyncio
import structlog
from sqlalchemy import or_, select

from src.agent.extractor import extract_agent_report
from src.db import get_async_session_factory
from src.models.analysis_result import AnalysisResult

logger = structlog.get_logger()


async def main() -> None:
    factory = get_async_session_factory()
    async with factory() as session:
        # Pick rows that don't yet have the new product fields populated.
        rows = (
            await session.execute(
                select(AnalysisResult).where(
                    or_(
                        AnalysisResult.product_idea.is_(None),
                        AnalysisResult.target_audience.is_(None),
                    )
                )
            )
        ).scalars().all()
        logger.info("backfill_start", candidates=len(rows))

        updated = 0
        for row in rows:
            trace = row.agent_trace or {}
            source = (
                trace.get("raw_report")
                or row.idea_description
                or row.idea_title
                or ""
            )
            if not source.strip():
                logger.info("backfill_skip", id=str(row.id), reason="empty_source")
                continue
            try:
                report = await extract_agent_report(source)
            except Exception:
                logger.exception("backfill_failed", id=str(row.id))
                continue
            row.idea_title = report.idea_title
            row.product_idea = report.product_idea
            row.target_audience = report.target_audience
            row.use_case = report.use_case
            row.pain_points = report.pain_points
            row.key_features = report.key_features
            row.overall_score = float(report.overall_score)
            updated += 1
            logger.info(
                "backfill_row",
                id=str(row.id),
                score=row.overall_score,
                title=row.idea_title[:60],
            )

        await session.commit()
        logger.info("backfill_done", updated=updated, total=len(rows))


if __name__ == "__main__":
    asyncio.run(main())
