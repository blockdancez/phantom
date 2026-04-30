"""Approval service: approve / reject / skip / rerun / abort。"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.engine.state_machine import (
    STEPS,
    State,
    next_running_state,
    transition,
)
from scheduler.observability import metrics
from scheduler.observability.logging import get_logger
from scheduler.storage.db import defer_xadd
from scheduler.storage.models import Approval, StepExecution, Workflow, WorkflowEvent

logger = get_logger(__name__)


class ApprovalService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def approve(
        self,
        *,
        workflow_id: uuid.UUID,
        step: str,
        comment: str | None,
        request_id: str,
    ) -> None:
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        target = next_running_state(src, policy=wf.approval_policy)
        transition(src, target)
        wf.status = target.value
        if target.value.endswith("_RUNNING"):
            wf.current_step = target.value.removesuffix("_RUNNING").lower()
        self._record_approval(wf, decision="approve", step=step, comment=comment)
        self._record_event(wf, src=src, dst=target, request_id=request_id)
        if target.value.endswith("_RUNNING"):
            await self._enqueue_step(
                wf,
                step=target.value.removesuffix("_RUNNING").lower(),
                request_id=request_id,
            )
        logger.info(
            "审批通过，推进工作流",
            workflow_id=str(workflow_id),
            step=step,
            from_state=src.value,
            to_state=target.value,
            request_id=request_id,
        )

    async def reject(
        self,
        *,
        workflow_id: uuid.UUID,
        step: str,
        comment: str | None,
        request_id: str,
    ) -> None:
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        transition(src, State.ABORTED)
        wf.status = State.ABORTED.value
        self._record_approval(wf, decision="reject", step=step, comment=comment)
        self._record_event(wf, src=src, dst=State.ABORTED, request_id=request_id)
        metrics.workflows_total.labels(status="ABORTED").inc()
        logger.info(
            "审批驳回，工作流中止",
            workflow_id=str(workflow_id),
            step=step,
            from_state=src.value,
            request_id=request_id,
        )

    async def abort(
        self,
        *,
        workflow_id: uuid.UUID,
        comment: str | None,
        request_id: str,
    ) -> None:
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        if src == State.ABORTED:
            logger.info(
                "工作流已中止，幂等忽略",
                workflow_id=str(workflow_id),
                request_id=request_id,
            )
            return
        transition(src, State.ABORTED)
        wf.status = State.ABORTED.value
        self._record_approval(wf, decision="abort", step=wf.current_step or "", comment=comment)
        self._record_event(wf, src=src, dst=State.ABORTED, request_id=request_id)
        metrics.workflows_total.labels(status="ABORTED").inc()
        logger.info(
            "工作流已中止",
            workflow_id=str(workflow_id),
            from_state=src.value,
            request_id=request_id,
        )

    async def rerun(
        self,
        *,
        workflow_id: uuid.UUID,
        step: str,
        modified_input: dict | None,
        comment: str | None,
        request_id: str,
    ) -> uuid.UUID:
        """从 AWAITING_MANUAL_ACTION 或 *_DONE 重跑指定 step。返回新 task_id。"""
        wf = await self._get_wf(workflow_id)
        src = State(wf.status)
        target_running = State[f"{step.upper()}_RUNNING"]
        transition(src, target_running)
        wf.status = target_running.value
        wf.current_step = step
        wf.failed_step = None
        if modified_input is not None:
            wf.input = modified_input
        self._record_approval(
            wf,
            decision="rerun",
            step=step,
            comment=comment,
            payload={"modified_input": modified_input} if modified_input else None,
        )
        self._record_event(wf, src=src, dst=target_running, request_id=request_id)
        new_id = await self._enqueue_step(wf, step=step, request_id=request_id)
        logger.info(
            "审批触发重跑",
            workflow_id=str(workflow_id),
            step=step,
            new_task_id=str(new_id),
            modified_input=bool(modified_input),
            request_id=request_id,
        )
        return new_id

    async def skip(
        self,
        *,
        workflow_id: uuid.UUID,
        comment: str | None,
        request_id: str,
    ) -> None:
        """跳过当前失败 step 推进到下一步（仅 AWAITING_MANUAL_ACTION）。"""
        wf = await self._get_wf(workflow_id)
        if State(wf.status) != State.AWAITING_MANUAL_ACTION or not wf.failed_step:
            raise ValueError("skip only valid in AWAITING_MANUAL_ACTION with failed_step")
        failed_idx = STEPS.index(wf.failed_step)
        if failed_idx == len(STEPS) - 1:
            target = State.COMPLETED
        else:
            next_step = STEPS[failed_idx + 1]
            policy = wf.approval_policy.get(next_step, "manual")
            if policy == "auto":
                target = State[f"{next_step.upper()}_RUNNING"]
            else:
                target = State[f"AWAITING_APPROVAL_{next_step.upper()}"]

        src = State(wf.status)
        transition(src, target)
        wf.status = target.value
        wf.failed_step = None
        self._record_approval(wf, decision="skip", step=STEPS[failed_idx], comment=comment)
        self._record_event(wf, src=src, dst=target, request_id=request_id)
        if target.value.endswith("_RUNNING"):
            await self._enqueue_step(
                wf,
                step=target.value.removesuffix("_RUNNING").lower(),
                request_id=request_id,
            )
        logger.info(
            "跳过失败步骤",
            workflow_id=str(workflow_id),
            failed_step=STEPS[failed_idx],
            to_state=target.value,
            request_id=request_id,
        )

    async def _get_wf(self, workflow_id: uuid.UUID) -> Workflow:
        result = await self.session.execute(select(Workflow).where(Workflow.id == workflow_id))
        wf = result.scalar_one_or_none()
        if wf is None:
            raise ValueError(f"Workflow {workflow_id} not found")
        return wf

    def _record_approval(
        self,
        wf: Workflow,
        *,
        decision: str,
        step: str,
        comment: str | None,
        payload: dict | None = None,
    ) -> None:
        self.session.add(
            Approval(
                workflow_id=wf.id,
                step=step,
                decision=decision,
                comment=comment,
                payload=payload,
            )
        )

    def _record_event(self, wf: Workflow, *, src: State, dst: State, request_id: str) -> None:
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": dst.value},
                request_id=request_id,
            )
        )

    async def _enqueue_step(self, wf: Workflow, *, step: str, request_id: str) -> uuid.UUID:
        result = await self.session.execute(
            select(StepExecution)
            .where(StepExecution.workflow_id == wf.id)
            .where(StepExecution.step == step)
        )
        existing = list(result.scalars().all())
        attempt = max((e.attempt for e in existing), default=0) + 1

        exec_ = StepExecution(
            workflow_id=wf.id,
            step=step,
            attempt=attempt,
            status="pending",
            input=wf.input,
            request_id=request_id,
        )
        self.session.add(exec_)
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="task.enqueued",
                payload={
                    "step": step,
                    "attempt": attempt,
                    "task_id": str(exec_.id),
                },
                request_id=request_id,
            )
        )
        await self.session.flush()
        defer_xadd(
            self.session,
            step=step,
            payload={
                "task_id": str(exec_.id),
                "workflow_id": str(wf.id),
                "project_name": wf.project_name,
                "step": step,
                "attempt": attempt,
                "input": wf.input,
                "artifact_root": wf.artifact_root,
                "request_id": request_id,
            },
        )
        return exec_.id
