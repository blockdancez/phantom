"""/api/workflows/<id>/approvals endpoints。"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session
from scheduler.api.schemas import ApprovalRequest
from scheduler.engine.approval_service import ApprovalService
from scheduler.engine.state_machine import InvalidTransition
from scheduler.observability.logging import get_logger, get_request_id

logger = get_logger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["approvals"])


@router.post("/{wf_id}/approvals")
async def submit_approval(
    wf_id: uuid.UUID,
    body: ApprovalRequest,
    session: AsyncSession = Depends(get_session),
) -> dict:
    svc = ApprovalService(session)
    rid = get_request_id() or "req_unknown"
    try:
        if body.decision == "approve":
            if not body.step:
                raise HTTPException(400, "step required for approve")
            await svc.approve(
                workflow_id=wf_id,
                step=body.step,
                comment=body.comment,
                request_id=rid,
            )
            logger.info(
                "审批通过",
                workflow_id=str(wf_id),
                step=body.step,
                request_id=rid,
            )
            return {"ok": True}
        if body.decision == "reject":
            if not body.step:
                raise HTTPException(400, "step required for reject")
            await svc.reject(
                workflow_id=wf_id,
                step=body.step,
                comment=body.comment,
                request_id=rid,
            )
            logger.info(
                "审批驳回",
                workflow_id=str(wf_id),
                step=body.step,
                request_id=rid,
            )
            return {"ok": True}
        if body.decision == "abort":
            await svc.abort(workflow_id=wf_id, comment=body.comment, request_id=rid)
            logger.info("中止工作流", workflow_id=str(wf_id), request_id=rid)
            return {"ok": True}
        if body.decision == "rerun":
            if not body.step:
                raise HTTPException(400, "step required for rerun")
            new_id = await svc.rerun(
                workflow_id=wf_id,
                step=body.step,
                modified_input=body.modified_input,
                comment=body.comment,
                request_id=rid,
            )
            logger.info(
                "重跑步骤",
                workflow_id=str(wf_id),
                step=body.step,
                new_task_id=str(new_id),
                request_id=rid,
            )
            return {"ok": True, "new_task_id": str(new_id)}
        if body.decision == "skip":
            await svc.skip(workflow_id=wf_id, comment=body.comment, request_id=rid)
            logger.info("跳过失败步骤", workflow_id=str(wf_id), request_id=rid)
            return {"ok": True}
        raise HTTPException(400, f"Unknown decision: {body.decision}")
    except InvalidTransition as e:
        logger.warning(
            "审批操作触发非法状态迁移",
            workflow_id=str(wf_id),
            decision=body.decision,
            error=str(e),
            request_id=rid,
        )
        raise HTTPException(409, str(e)) from e
    except ValueError as e:
        raise HTTPException(400, str(e)) from e
