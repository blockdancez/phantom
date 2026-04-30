"""/api/tasks endpoints（agent SDK 调用）。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session, settings_dep
from scheduler.api.schemas import (
    TaskCompleteRequest,
    TaskFailRequest,
    TaskHeartbeatRequest,
    TaskStartRequest,
)
from scheduler.config import Settings
from scheduler.engine.state_machine import InvalidTransition
from scheduler.engine.task_service import TaskService
from scheduler.observability.logging import get_logger, get_request_id

logger = get_logger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


@router.put("/{task_id}/start")
async def start_task(
    task_id: uuid.UUID,
    body: TaskStartRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> dict:
    svc = TaskService(session, max_retries=settings.max_retries)
    rid = get_request_id() or "req_unknown"
    try:
        started = await svc.start(task_id=task_id, agent_id=body.agent_id, request_id=rid)
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    logger.info(
        "Agent 接收任务",
        task_id=str(task_id),
        agent_id=body.agent_id,
        started=started,
        request_id=rid,
    )
    return {"ok": True, "started": started}


@router.put("/{task_id}/complete")
async def complete_task(
    task_id: uuid.UUID,
    body: TaskCompleteRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> dict:
    svc = TaskService(session, max_retries=settings.max_retries)
    rid = get_request_id() or "req_unknown"
    try:
        await svc.complete(task_id=task_id, output=body.output, request_id=rid)
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    logger.info("任务执行完成", task_id=str(task_id), request_id=rid)
    return {"ok": True}


@router.put("/{task_id}/fail")
async def fail_task(
    task_id: uuid.UUID,
    body: TaskFailRequest,
    session: AsyncSession = Depends(get_session),
    settings: Settings = Depends(settings_dep),
) -> dict:
    svc = TaskService(session, max_retries=settings.max_retries)
    rid = get_request_id() or "req_unknown"
    try:
        new_id = await svc.fail(
            task_id=task_id,
            error=body.error,
            retryable=body.retryable,
            request_id=rid,
        )
    except InvalidTransition as e:
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
    logger.info(
        "任务执行失败",
        task_id=str(task_id),
        retryable=body.retryable,
        new_task_id=str(new_id) if new_id else None,
        request_id=rid,
    )
    return {"ok": True, "new_task_id": str(new_id) if new_id else None}


@router.put("/{task_id}/heartbeat")
async def heartbeat(
    task_id: uuid.UUID,
    body: TaskHeartbeatRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    svc = TaskService(session)
    await svc.heartbeat(task_id=task_id, message=body.message)
    logger.debug(
        "任务心跳",
        task_id=str(task_id),
        request_id=get_request_id() or "req_unknown",
    )
    return {"ok": True}
