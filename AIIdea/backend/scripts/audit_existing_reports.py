"""Re-run the critique_idea tool on every existing AnalysisResult and emit
a report showing which ones fail the new hard constraints (including the
newly-added ``solution_fit`` axis).

This is a dry-run audit; it does NOT delete anything. User reviews the
output, then decides whether to purge the failures.

Usage:
    DATABASE_URL=... OPENAI_API_KEY=... PYTHONPATH=. \\
        python scripts/audit_existing_reports.py
"""

from __future__ import annotations

import asyncio
import json
import re

import structlog
from sqlalchemy import select

from src.agent.tools.critique_idea import critique_idea
from src.db import get_async_session_factory
from src.models.analysis_result import AnalysisResult

logger = structlog.get_logger()


def _extract_json(text: str) -> dict | None:
    """The critique tool returns JSON optionally wrapped in ```json fences."""
    if not text:
        return None
    cleaned = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip(), flags=re.MULTILINE)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        return None


async def main() -> None:
    factory = get_async_session_factory()
    async with factory() as session:
        rows = (
            await session.execute(
                select(AnalysisResult).order_by(AnalysisResult.created_at.desc())
            )
        ).scalars().all()
        logger.info("audit_start", total=len(rows))

        pass_count = 0
        reject_count = 0
        rejects: list[dict] = []

        for row in rows:
            if not row.user_story or not row.idea_title:
                logger.info("audit_skip", id=str(row.id), reason="missing_fields")
                continue

            raw = await critique_idea.ainvoke(
                {
                    "idea_title": row.idea_title,
                    "user_story": row.user_story,
                    "anchor_quote": row.source_quote or "",
                    "key_features": row.key_features or "",
                }
            )
            verdict = _extract_json(raw)
            if verdict is None:
                logger.warning("audit_parse_failed", id=str(row.id))
                continue

            overall = verdict.get("overall", "unknown")
            if overall == "pass":
                pass_count += 1
                logger.info("audit_pass", id=str(row.id), title=row.idea_title[:60])
            else:
                reject_count += 1
                reasons = verdict.get("hard_reject_reasons") or []
                logger.info(
                    "audit_reject",
                    id=str(row.id),
                    title=row.idea_title[:60],
                    reasons=reasons,
                )
                rejects.append(
                    {
                        "id": str(row.id),
                        "title": row.idea_title,
                        "reasons": reasons,
                        "solution_fit": verdict.get("solution_fit"),
                        "technical_feasibility": verdict.get("technical_feasibility"),
                    }
                )

        logger.info("audit_done", pass_count=pass_count, reject_count=reject_count)
        print("\n=== Reports that FAIL the new critique ===")
        for r in rejects:
            print(f"  {r['id']}  {r['title']}")
            for reason in r["reasons"]:
                print(f"    - {reason}")


if __name__ == "__main__":
    asyncio.run(main())
