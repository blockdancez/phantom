"""/api/dashboard endpoints —— 主页用的总览数据。

提供两类数据：
1. 待办事项（需要用户处理的工作流）：AWAITING_APPROVAL_* / AWAITING_MANUAL_ACTION
2. 各步骤 × 各状态的数据量：用于绘制状态分布矩阵
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session
from scheduler.api.schemas import WorkflowRead
from scheduler.engine.state_machine import STEPS
from scheduler.observability.logging import get_logger
from scheduler.storage.models import Workflow

logger = get_logger(__name__)
router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])


@router.get("/summary")
async def dashboard_summary(
    session: AsyncSession = Depends(get_session),
) -> dict[str, Any]:
    # ── 1. 待办事项 ──
    pending_stmt = (
        select(Workflow)
        .where(
            (Workflow.status.like("AWAITING_APPROVAL_%"))
            | (Workflow.status == "AWAITING_MANUAL_ACTION")
        )
        .order_by(Workflow.updated_at.desc())
        .limit(50)
    )
    pending_rows = list((await session.execute(pending_stmt)).scalars().all())
    pending = [WorkflowRead.model_validate(w) for w in pending_rows]

    # ── 2. 全部 status 计数 ──
    count_stmt = select(Workflow.status, func.count()).group_by(Workflow.status)
    rows = (await session.execute(count_stmt)).all()
    status_counts: dict[str, int] = {row[0]: int(row[1]) for row in rows}

    # ── 3. 每个 failed_step 的人工介入数（用于 step×failed 矩阵） ──
    failed_stmt = (
        select(Workflow.failed_step, func.count())
        .where(Workflow.status == "AWAITING_MANUAL_ACTION")
        .group_by(Workflow.failed_step)
    )
    failed_by_step: dict[str, int] = {}
    for s, n in (await session.execute(failed_stmt)).all():
        if s:
            failed_by_step[s] = int(n)

    # ── 4. 派生：step × state 矩阵 ──
    # 列（状态）：running / awaiting / failed / done / total
    # awaiting：在 AWAITING_APPROVAL_<NEXT> 时，UI 语义把"待审批"挂在 prev 步上
    grid: dict[str, dict[str, int]] = {
        s: {"running": 0, "awaiting": 0, "failed": 0, "done": 0} for s in STEPS
    }
    for status, n in status_counts.items():
        if status.endswith("_RUNNING"):
            step = status[: -len("_RUNNING")].lower()
            if step in grid:
                grid[step]["running"] += n
        elif status.endswith("_DONE"):
            step = status[: -len("_DONE")].lower()
            if step in grid:
                grid[step]["done"] += n
        elif status.startswith("AWAITING_APPROVAL_"):
            next_step = status[len("AWAITING_APPROVAL_") :].lower()
            idx = STEPS.index(next_step) if next_step in STEPS else -1
            if idx > 0:
                # awaiting 挂在上一步（刚产出待审）
                grid[STEPS[idx - 1]]["awaiting"] += n
    for step, n in failed_by_step.items():
        if step in grid:
            grid[step]["failed"] += n

    # ── 5. 全局 status 分组汇总 ──
    totals = {
        "running": sum(n for s, n in status_counts.items() if s.endswith("_RUNNING")),
        "awaiting": sum(n for s, n in status_counts.items() if s.startswith("AWAITING_APPROVAL_")),
        "manual": status_counts.get("AWAITING_MANUAL_ACTION", 0),
        "completed": status_counts.get("COMPLETED", 0),
        "aborted": status_counts.get("ABORTED", 0),
        "total": sum(status_counts.values()),
    }

    logger.info(
        "查询仪表盘汇总",
        pending=len(pending),
        total=totals["total"],
    )
    return {
        "pending": [w.model_dump(mode="json") for w in pending],
        "totals": totals,
        "grid": grid,
        "status_counts": status_counts,
    }
