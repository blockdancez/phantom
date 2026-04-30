"""/api/workflows endpoints。"""

from __future__ import annotations

import shutil
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session, settings_dep
from scheduler.api.schemas import WorkflowCreate, WorkflowListResponse, WorkflowRead
from scheduler.config import Settings
from scheduler.engine.workflow_service import WorkflowService
from scheduler.observability.logging import get_logger, get_request_id
from scheduler.storage.models import Workflow

logger = get_logger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.post("", response_model=WorkflowRead, status_code=201)
async def create_workflow(
    body: WorkflowCreate,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> WorkflowRead:
    service = WorkflowService(session, artifact_root=settings.artifact_root)
    rid = get_request_id() or "req_unknown"
    wf_id = await service.create(
        name=body.name,
        project_name=body.project_name,
        input=body.input,
        approval_policy=body.approval_policy,
        initial_artifacts=[a.model_dump() for a in body.initial_artifacts],
        request_id=rid,
    )
    wf = await service.get(wf_id)
    assert wf is not None
    logger.info("创建工作流成功", workflow_id=str(wf_id), request_id=rid)
    return WorkflowRead.model_validate(wf)


@router.get("", response_model=WorkflowListResponse)
async def list_workflows(
    q: str | None = Query(default=None, description="name 模糊搜索（不区分大小写）"),
    status: str | None = Query(default=None, description="状态精确匹配"),
    status_group: str | None = Query(
        default=None,
        description="按分组筛选：running / awaiting / manual / completed / aborted / active",
    ),
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=200),
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> WorkflowListResponse:
    service = WorkflowService(session, artifact_root=settings.artifact_root)
    items, total = await service.list_with_count(
        q=q,
        status=status,
        status_group=status_group,
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    logger.info(
        "查询工作流列表",
        count=len(items),
        total=total,
        q=q,
        status=status,
        status_group=status_group,
        page=page,
        page_size=page_size,
        request_id=get_request_id() or "req_unknown",
    )
    return WorkflowListResponse(
        items=[WorkflowRead.model_validate(i) for i in items],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{wf_id}", response_model=WorkflowRead)
async def get_workflow(
    wf_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> WorkflowRead:
    service = WorkflowService(session, artifact_root=settings.artifact_root)
    wf = await service.get(wf_id)
    if wf is None:
        logger.info(
            "查询工作流不存在",
            workflow_id=str(wf_id),
            request_id=get_request_id() or "req_unknown",
        )
        raise HTTPException(status_code=404, detail="Workflow not found")
    logger.info(
        "查询工作流详情",
        workflow_id=str(wf_id),
        request_id=get_request_id() or "req_unknown",
    )
    return WorkflowRead.model_validate(wf)


@router.get("/{wf_id}/history")
async def get_workflow_history(
    wf_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[dict]:
    """合并"审批/重跑动作"（approvals 表）和"产物编辑"（workflow_events.artifact.edited）
    两条来源，按时间倒序返回。用于 UI 详情页的修改 / 重跑历史面板。
    """
    from sqlalchemy import select

    from scheduler.storage.models import Approval, WorkflowEvent  # noqa: PLC0415

    # approvals 表：approve / reject / rerun / skip / abort
    appr_stmt = (
        select(Approval).where(Approval.workflow_id == wf_id).order_by(Approval.created_at.desc())
    )
    appr_rows = list((await session.execute(appr_stmt)).scalars().all())

    # workflow_events 里的 artifact.edited
    ev_stmt = (
        select(WorkflowEvent)
        .where(WorkflowEvent.workflow_id == wf_id)
        .where(WorkflowEvent.event_type == "artifact.edited")
        .order_by(WorkflowEvent.created_at.desc())
    )
    ev_rows = list((await session.execute(ev_stmt)).scalars().all())

    items: list[dict] = []
    for a in appr_rows:
        items.append(
            {
                "kind": "approval",
                "decision": a.decision,
                "step": a.step,
                "comment": a.comment,
                "payload": a.payload,
                "created_at": a.created_at.isoformat(),
            }
        )
    for e in ev_rows:
        items.append(
            {
                "kind": "artifact_edited",
                "step": (e.payload or {}).get("step"),
                "key": (e.payload or {}).get("key"),
                "comment": (e.payload or {}).get("comment"),
                "payload": e.payload,
                "request_id": e.request_id,
                "created_at": e.created_at.isoformat(),
            }
        )
    items.sort(key=lambda x: x["created_at"], reverse=True)
    return items[:200]


@router.delete("/{wf_id}", status_code=204)
async def delete_workflow(
    wf_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> None:
    """彻底删除一个 workflow 及其全部关联：
    - DB：workflows + cascade（step_executions / artifacts / approvals / workflow_events）
    - FS：artifact_root 目录
    - Redis：tasks:<step> stream 中属于该工作流的 payload（XACK + XDEL）
    """
    from sqlalchemy import select

    from scheduler.api import get_database  # noqa: PLC0415 — 避免循环依赖

    wf = (await session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one_or_none()
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")

    artifact_root = Path(wf.artifact_root)
    await session.execute(delete(Workflow).where(Workflow.id == wf_id))

    # FS 清理（失败不影响 DB 删除；只记录告警）
    if artifact_root.exists():
        try:
            shutil.rmtree(artifact_root)
        except OSError as e:
            logger.warning(
                "删除工作流时清理产物目录失败",
                workflow_id=str(wf_id),
                path=str(artifact_root),
                error=str(e),
            )

    # Redis 清理：从所有 step 的 stream 里抹掉属于该工作流的消息
    try:
        tq = get_database().task_queue
        if tq is not None:
            purged = await tq.purge_workflow(str(wf_id))
            if any(v for v in purged.values()):
                logger.info(
                    "删除工作流时已清理 Redis 残留",
                    workflow_id=str(wf_id),
                    purged=purged,
                )
    except Exception as e:  # noqa: BLE001 — Redis 残留清不掉不阻塞删除
        logger.warning(
            "删除工作流时清理 Redis 残留失败",
            workflow_id=str(wf_id),
            error=str(e),
        )

    logger.info(
        "删除工作流成功",
        workflow_id=str(wf_id),
        request_id=get_request_id() or "req_unknown",
    )
