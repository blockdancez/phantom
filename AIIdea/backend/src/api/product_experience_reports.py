"""Product experience report endpoints.

List + detail under /api/product-experience-reports. Mirrors the shape of
src.api.analysis_results — relies on the global EnvelopeMiddleware to wrap
returned pydantic models in `{code, message, data, request_id}`.
"""

import uuid

import structlog
from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db import get_session
from src.exceptions import APIError, ErrorCode
from src.models.product_experience_report import ProductExperienceReport
from src.schemas.product_experience_report import (
    ProductExperienceListResponse,
    ProductExperienceReportListOut,
    ProductExperienceReportOut,
)

router = APIRouter()
logger = structlog.get_logger()


@router.get(
    "/product-experience-reports", response_model=ProductExperienceListResponse
)
async def list_product_experience_reports(
    page: int = Query(1, ge=1),
    per_page: int = Query(20, ge=1, le=100),
    product_slug: str | None = Query(None),
    q: str | None = Query(
        None,
        description="Free-text search across product_name / product_url / summary_zh.",
    ),
    status: str | None = Query(
        None,
        pattern="^(completed|partial|failed)$",
    ),
    min_score: float | None = Query(None, ge=0.0, le=10.0),
    sort: str = Query(
        "started_at",
        pattern="^(started_at|completed_at|score)$",
        description="Sort field. Default: started_at (newest first).",
    ),
    order: str = Query(
        "desc",
        pattern="^(asc|desc)$",
        description="Sort direction (default desc).",
    ),
    session: AsyncSession = Depends(get_session),
) -> ProductExperienceListResponse:
    logger.info(
        "查询产品体验列表",
        page=page,
        per_page=per_page,
        product_slug=product_slug,
        q=q,
        status=status,
        min_score=min_score,
        sort=sort,
        order=order,
    )

    base = select(ProductExperienceReport)
    if product_slug:
        base = base.where(ProductExperienceReport.product_slug == product_slug)
    if q:
        like = f"%{q}%"
        base = base.where(
            or_(
                ProductExperienceReport.product_name.ilike(like),
                ProductExperienceReport.product_url.ilike(like),
                ProductExperienceReport.summary_zh.ilike(like),
            )
        )
    if status:
        base = base.where(ProductExperienceReport.status == status)
    if min_score is not None:
        base = base.where(ProductExperienceReport.overall_ux_score >= min_score)

    total = (
        await session.execute(select(func.count()).select_from(base.subquery()))
    ).scalar_one()

    sort_col = {
        "started_at": ProductExperienceReport.run_started_at,
        "completed_at": ProductExperienceReport.run_completed_at,
        "score": ProductExperienceReport.overall_ux_score,
    }[sort]
    primary = sort_col.desc() if order == "desc" else sort_col.asc()
    # Stable tie-break on the *other* columns desc.
    secondary = ProductExperienceReport.run_started_at.desc()

    rows = (
        await session.execute(
            base.order_by(primary, secondary)
            .offset((page - 1) * per_page)
            .limit(per_page)
        )
    ).scalars().all()

    items = [
        ProductExperienceReportListOut(
            id=r.id,
            product_slug=r.product_slug,
            product_name=r.product_name,
            product_url=r.product_url,
            project_name=r.project_name,
            aijuicer_workflow_id=r.aijuicer_workflow_id,
            run_completed_at=r.run_completed_at,
            status=r.status,
            login_used=r.login_used,
            overall_ux_score=r.overall_ux_score,
            product_thesis=r.product_thesis,
            summary_zh=r.summary_zh,
            screenshots_count=len(r.screenshots) if r.screenshots else 0,
        )
        for r in rows
    ]
    return ProductExperienceListResponse(
        items=items, total=total, page=page, per_page=per_page
    )


@router.get(
    "/product-experience-reports/{report_id}",
    response_model=ProductExperienceReportOut,
)
async def get_product_experience_report(
    report_id: str,
    session: AsyncSession = Depends(get_session),
) -> ProductExperienceReportOut:
    logger.info("查询产品体验详情", report_id=report_id)

    try:
        parsed_id = uuid.UUID(report_id)
    except (ValueError, TypeError):
        raise APIError(
            code=ErrorCode.PRODUCT_EXPERIENCE_BAD_ID,
            message=f"'{report_id}' is not a valid UUID",
            http_status=400,
        )

    row = (
        await session.execute(
            select(ProductExperienceReport).where(
                ProductExperienceReport.id == parsed_id
            )
        )
    ).scalar_one_or_none()
    if row is None:
        raise APIError(
            code=ErrorCode.PRODUCT_EXPERIENCE_NOT_FOUND,
            message="product experience report not found",
            http_status=404,
        )

    return ProductExperienceReportOut.model_validate(row)
