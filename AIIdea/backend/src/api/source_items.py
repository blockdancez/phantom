import uuid
from datetime import datetime, timezone

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.exceptions import APIError, ErrorCode
from src.models.analysis_result import AnalysisResult
from src.models.source_item import SourceItem
from src.schemas.source_item import SourceItemList, SourceItemRead

router = APIRouter()
logger = structlog.get_logger()


# Allowed sort keys → SQLAlchemy column
_SORT_KEYS = {
    "collected_at": SourceItem.collected_at,
    "score": SourceItem.score,
    "title": SourceItem.title,
}


def _parse_dt(value: str | None, field: str) -> datetime | None:
    if value is None:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise APIError(
            code=ErrorCode.BAD_REQUEST,
            message=f"invalid {field}: expected ISO-8601 datetime",
            http_status=400,
        ) from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


async def _analysis_id_map(
    session: AsyncSession, source_item_ids: list[uuid.UUID]
) -> dict[uuid.UUID, uuid.UUID]:
    """Return {source_item_id: analysis_result_id} for the given items.

    feature-9 requires that ``/sources/[id]`` surfaces a "查看分析" button
    pointing at the AnalysisResult derived from that SourceItem. We look up
    matches in bulk to keep list-page latency flat.
    """
    if not source_item_ids:
        return {}
    stmt = (
        select(AnalysisResult.id, AnalysisResult.source_item_id)
        .where(AnalysisResult.source_item_id.in_(source_item_ids))
        .order_by(AnalysisResult.created_at.desc())
    )
    rows = (await session.execute(stmt)).all()
    mapping: dict[uuid.UUID, uuid.UUID] = {}
    for result_id, source_id in rows:
        # Keep the newest analysis if multiple runs referenced the same item.
        if source_id not in mapping:
            mapping[source_id] = result_id
    return mapping


@router.get("/source-items", response_model=SourceItemList)
async def list_source_items(
    page: int = Query(1, ge=1),
    per_page: int | None = Query(
        None,
        ge=1,
        le=200,
        description="Page size (plan contract name). If both per_page and page_size are provided, per_page wins.",
    ),
    page_size: int | None = Query(
        None,
        ge=1,
        le=200,
        description="Legacy page-size alias; kept for backward compatibility.",
    ),
    source: str | None = None,
    category: str | None = None,
    min_score: float | None = Query(None, ge=0.0, le=100.0),
    processed: bool | None = Query(None, description="Filter by processed status"),
    q: str | None = Query(None, description="Full-text search in title/content"),
    collected_since: str | None = Query(
        None,
        description="ISO-8601 datetime lower bound on collected_at (inclusive)",
    ),
    collected_until: str | None = Query(
        None,
        description="ISO-8601 datetime upper bound on collected_at (inclusive)",
    ),
    sort: str = Query("collected_at", pattern="^(collected_at|score|title)$"),
    order: str = Query("desc", pattern="^(asc|desc)$"),
    session: AsyncSession = Depends(get_session),
) -> SourceItemList:
    effective_per_page = per_page if per_page is not None else page_size
    if effective_per_page is None:
        effective_per_page = 20

    since_dt = _parse_dt(collected_since, "collected_since")
    until_dt = _parse_dt(collected_until, "collected_until")

    logger.info(
        "查询数据条目列表",
        page=page,
        per_page=effective_per_page,
        source=source,
        category=category,
        processed=processed,
        q=q,
        sort=sort,
        order=order,
        collected_since=collected_since,
        collected_until=collected_until,
    )

    base = select(SourceItem)
    if source:
        base = base.where(SourceItem.source == source)
    if category:
        base = base.where(SourceItem.category == category)
    if min_score is not None:
        base = base.where(SourceItem.score >= min_score)
    if processed is not None:
        base = base.where(SourceItem.processed.is_(processed))
    if q:
        like = f"%{q}%"
        base = base.where(
            or_(SourceItem.title.ilike(like), SourceItem.content.ilike(like))
        )
    if since_dt is not None:
        base = base.where(SourceItem.collected_at >= since_dt)
    if until_dt is not None:
        base = base.where(SourceItem.collected_at <= until_dt)

    sort_col = _SORT_KEYS[sort]
    sort_expr = sort_col.desc() if order == "desc" else sort_col.asc()
    sort_expr_secondary = SourceItem.id.desc()

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    items_stmt = (
        base.order_by(sort_expr, sort_expr_secondary)
        .offset((page - 1) * effective_per_page)
        .limit(effective_per_page)
    )
    items = (await session.execute(items_stmt)).scalars().all()

    analysis_map = await _analysis_id_map(session, [i.id for i in items])
    reads: list[SourceItemRead] = []
    for i in items:
        record = SourceItemRead.model_validate(i)
        record.analysis_result_id = analysis_map.get(i.id)
        reads.append(record)

    return SourceItemList(
        items=reads,
        total=total,
        page=page,
        per_page=effective_per_page,
    )


@router.get("/source-items/{item_id}", response_model=SourceItemRead)
async def get_source_item(
    item_id: str,
    session: AsyncSession = Depends(get_session),
) -> SourceItemRead:
    logger.info("查询数据条目详情", item_id=item_id)

    try:
        parsed_id = uuid.UUID(item_id)
    except (ValueError, TypeError):
        raise APIError(
            code=ErrorCode.SOURCE_ITEM_BAD_ID,
            message=f"'{item_id}' is not a valid UUID",
            http_status=400,
        )

    stmt = select(SourceItem).where(SourceItem.id == parsed_id)
    item = (await session.execute(stmt)).scalar_one_or_none()
    if item is None:
        raise APIError(
            code=ErrorCode.SOURCE_ITEM_NOT_FOUND,
            message="source item not found",
            http_status=404,
        )
    record = SourceItemRead.model_validate(item)
    analysis_map = await _analysis_id_map(session, [item.id])
    record.analysis_result_id = analysis_map.get(item.id)
    return record
