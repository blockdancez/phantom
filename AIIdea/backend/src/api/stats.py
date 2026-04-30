"""Aggregate + pipeline status endpoints."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Awaitable, Callable, TypeVar

import structlog
from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel
from sqlalchemy import case, func, select
from sqlalchemy.exc import DBAPIError, OperationalError, SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.exceptions import APIError, ErrorCode
from src.models.analysis_result import AnalysisResult
from src.models.source_item import SourceItem
from src.scheduler import runs as run_registry

router = APIRouter()
logger = structlog.get_logger()

T = TypeVar("T")


async def _db_guard(name: str, coro: Awaitable[T]) -> T:
    """Run a DB coroutine and raise ``APIError(503)`` on driver / operational
    failures. Per plan feature-7: /stats/sources and /stats/pipeline must
    surface DB unreachability as 503, not bubble up to the generic 500
    handler.
    """
    try:
        return await coro
    except (OperationalError, DBAPIError, SQLAlchemyError, ConnectionError) as exc:
        logger.error(
            "统计接口数据库不可达",
            endpoint=name,
            error_type=type(exc).__name__,
            error=str(exc)[:200],
        )
        raise APIError(
            code=ErrorCode.STATS_UNAVAILABLE,
            message="database not reachable",
            http_status=503,
        ) from exc


class SourceStat(BaseModel):
    source: str
    count: int
    last_collected_at: datetime | None
    unprocessed: int
    avg_score: float | None


class SourceStatsList(BaseModel):
    items: list[SourceStat]
    total_sources: int
    total_items: int
    recent_24h: int


class JobInfo(BaseModel):
    id: str
    name: str
    next_run_time: datetime | None
    trigger: str
    last_run_at: datetime | None
    last_status: str | None
    last_duration_ms: int | None
    last_error: str | None


class PipelineStatus(BaseModel):
    total_items: int
    processed_items: int
    unprocessed_items: int
    last_collected_at: datetime | None
    analysis_count: int
    last_analysis_at: datetime | None
    distinct_sources: int
    scheduler_alive: bool
    jobs: list[JobInfo]


def _exec(session: AsyncSession, stmt: Any) -> Callable[[], Awaitable[Any]]:
    async def _run():
        return await session.execute(stmt)

    return _run


@router.get("/stats/sources", response_model=SourceStatsList)
async def sources_stats(
    session: AsyncSession = Depends(get_session),
) -> SourceStatsList:
    logger.info("查询来源统计")

    stmt = (
        select(
            SourceItem.source,
            func.count().label("count"),
            func.max(SourceItem.collected_at).label("last_collected_at"),
            func.sum(case((SourceItem.processed.is_(False), 1), else_=0)).label(
                "unprocessed"
            ),
            func.avg(SourceItem.score).label("avg_score"),
        )
        .group_by(SourceItem.source)
        .order_by(func.count().desc())
    )
    rows_result = await _db_guard("stats_sources", session.execute(stmt))
    rows = rows_result.all()

    items = [
        SourceStat(
            source=r[0],
            count=int(r[1]),
            last_collected_at=r[2],
            unprocessed=int(r[3] or 0),
            avg_score=(float(r[4]) if r[4] is not None else None),
        )
        for r in rows
    ]

    total_items_stmt = select(func.count()).select_from(SourceItem)
    total_items_result = await _db_guard(
        "stats_sources", session.execute(total_items_stmt)
    )
    total_items = total_items_result.scalar_one()

    recent_stmt = select(func.count()).where(
        SourceItem.collected_at >= func.now() - func.make_interval(0, 0, 0, 1)
    )
    try:
        recent_24h_result = await session.execute(recent_stmt)
        recent_24h = int(recent_24h_result.scalar_one() or 0)
    except (OperationalError, DBAPIError, SQLAlchemyError, ConnectionError) as exc:
        # Distinguish real outage from Postgres-specific ``make_interval`` not
        # being available on a test dialect. Re-raise as 503 if the earlier
        # _db_guard already passed (so the DB is reachable but this query is
        # unsupported) we silently fall back to 0; otherwise DB is broken and
        # the earlier _db_guard would already have raised.
        logger.info(
            "近 24h 统计回落到 0",
            error_type=type(exc).__name__,
        )
        recent_24h = 0

    return SourceStatsList(
        items=items,
        total_sources=len(items),
        total_items=int(total_items),
        recent_24h=recent_24h,
    )


@router.get("/stats/pipeline", response_model=PipelineStatus)
async def pipeline_status(
    request: Request,
    session: AsyncSession = Depends(get_session),
) -> PipelineStatus:
    logger.info("查询管线状态")

    total_items_stmt = select(func.count()).select_from(SourceItem)
    total_items_result = await _db_guard(
        "stats_pipeline", session.execute(total_items_stmt)
    )
    total_items = int(total_items_result.scalar_one() or 0)

    processed_stmt = select(
        func.sum(case((SourceItem.processed.is_(True), 1), else_=0)),
        func.sum(case((SourceItem.processed.is_(False), 1), else_=0)),
        func.max(SourceItem.collected_at),
        func.count(func.distinct(SourceItem.source)),
    )
    processed_row_result = await _db_guard(
        "stats_pipeline", session.execute(processed_stmt)
    )
    processed_row = processed_row_result.one()
    processed_items = int(processed_row[0] or 0)
    unprocessed_items = int(processed_row[1] or 0)
    last_collected_at: datetime | None = processed_row[2]
    distinct_sources = int(processed_row[3] or 0)

    analysis_stmt = select(
        func.count(), func.max(AnalysisResult.created_at)
    ).select_from(AnalysisResult)
    analysis_row_result = await _db_guard(
        "stats_pipeline", session.execute(analysis_stmt)
    )
    analysis_row = analysis_row_result.one()
    analysis_count = int(analysis_row[0] or 0)
    last_analysis_at: datetime | None = analysis_row[1]

    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_alive = bool(scheduler and scheduler.running)

    run_snapshot = run_registry.all_last_runs()
    jobs: list[JobInfo] = []
    if scheduler is not None:
        for job in scheduler.get_jobs():
            last = run_snapshot.get(job.id)
            jobs.append(
                JobInfo(
                    id=job.id,
                    name=job.name or job.id,
                    next_run_time=job.next_run_time,
                    trigger=str(job.trigger),
                    last_run_at=(last.started_at if last else None),
                    last_status=(last.status if last else None),
                    last_duration_ms=(last.duration_ms if last else None),
                    last_error=(last.error if last else None),
                )
            )
    else:
        # Scheduler is offline but we still surface history so the dashboard
        # can show what happened before shutdown.
        for job_id, last in run_snapshot.items():
            jobs.append(
                JobInfo(
                    id=job_id,
                    name=job_id,
                    next_run_time=None,
                    trigger="",
                    last_run_at=last.started_at,
                    last_status=last.status,
                    last_duration_ms=last.duration_ms,
                    last_error=last.error,
                )
            )

    return PipelineStatus(
        total_items=total_items,
        processed_items=processed_items,
        unprocessed_items=unprocessed_items,
        last_collected_at=last_collected_at,
        analysis_count=analysis_count,
        last_analysis_at=last_analysis_at,
        distinct_sources=distinct_sources,
        scheduler_alive=scheduler_alive,
        jobs=jobs,
    )
