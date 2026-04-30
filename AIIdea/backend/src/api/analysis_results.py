import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.exceptions import APIError, ErrorCode
from src.models.analysis_result import AnalysisResult
from src.models.source_item import SourceItem
from src.schemas.analysis_result import AnalysisResultList, AnalysisResultRead

router = APIRouter()
logger = structlog.get_logger()


async def _augment_with_source_item(
    session: AsyncSession, result: AnalysisResult
) -> AnalysisResultRead:
    """Attach the anchor SourceItem's title/url to the response."""
    record = AnalysisResultRead.model_validate(result)
    if result.source_item_id:
        item = (
            await session.execute(
                select(SourceItem).where(SourceItem.id == result.source_item_id)
            )
        ).scalar_one_or_none()
        if item is not None:
            record.source_item_title = item.title
            record.source_item_url = item.url
    return record


@router.get("/analysis-results", response_model=AnalysisResultList)
async def list_analysis_results(
    page: int = Query(1, ge=1),
    per_page: int | None = Query(None, ge=1, le=200),
    page_size: int | None = Query(
        None,
        ge=1,
        le=200,
        description="Legacy page-size alias; kept for backward compatibility.",
    ),
    min_score: float | None = Query(None, ge=0.0, le=100.0),
    sort: str = Query(
        "created_at",
        pattern="^(created_at|score)$",
        description="Sort field. Default: created_at (newest first). 'score' sorts by overall_score.",
    ),
    order: str = Query(
        "desc",
        pattern="^(asc|desc)$",
        description="Sort direction (default desc).",
    ),
    session: AsyncSession = Depends(get_session),
) -> AnalysisResultList:
    effective_per_page = per_page if per_page is not None else page_size
    if effective_per_page is None:
        effective_per_page = 20

    logger.info(
        "查询创意 IDEA 列表",
        page=page,
        per_page=effective_per_page,
        min_score=min_score,
        order=order,
    )

    base = select(AnalysisResult)
    if min_score is not None:
        base = base.where(AnalysisResult.overall_score >= min_score)

    count_stmt = select(func.count()).select_from(base.subquery())
    total = (await session.execute(count_stmt)).scalar_one()

    primary_col = (
        AnalysisResult.created_at if sort == "created_at" else AnalysisResult.overall_score
    )
    primary = primary_col.desc() if order == "desc" else primary_col.asc()
    # Always tie-break on the *other* column descending so two rows with
    # equal primary value land in a stable order rather than DB-arbitrary.
    secondary = (
        AnalysisResult.overall_score.desc()
        if sort == "created_at"
        else AnalysisResult.created_at.desc()
    )

    items_stmt = (
        base.order_by(primary, secondary)
        .offset((page - 1) * effective_per_page)
        .limit(effective_per_page)
    )
    items = (await session.execute(items_stmt)).scalars().all()

    return AnalysisResultList(
        items=[await _augment_with_source_item(session, i) for i in items],
        total=total,
        page=page,
        per_page=effective_per_page,
    )


@router.get("/analysis-results/{result_id}", response_model=AnalysisResultRead)
async def get_analysis_result(
    result_id: str,
    session: AsyncSession = Depends(get_session),
) -> AnalysisResultRead:
    logger.info("查询创意 IDEA 详情", result_id=result_id)

    try:
        parsed_id = uuid.UUID(result_id)
    except (ValueError, TypeError):
        raise APIError(
            code=ErrorCode.ANALYSIS_BAD_ID,
            message=f"'{result_id}' is not a valid UUID",
            http_status=400,
        )

    stmt = select(AnalysisResult).where(AnalysisResult.id == parsed_id)
    result = (await session.execute(stmt)).scalar_one_or_none()

    if not result:
        raise APIError(
            code=ErrorCode.ANALYSIS_NOT_FOUND,
            message="analysis result not found",
            http_status=404,
        )

    return await _augment_with_source_item(session, result)
