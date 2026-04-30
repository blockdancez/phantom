"""Task lifecycle service: start / complete / fail / heartbeat。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.engine.state_machine import State, transition
from scheduler.engine.workflow_service import WorkflowService
from scheduler.observability import metrics
from scheduler.observability.logging import get_logger
from scheduler.storage.db import defer_xadd
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent

logger = get_logger(__name__)


class TaskService:
    def __init__(self, session: AsyncSession, *, max_retries: int = 3) -> None:
        self.session = session
        self.max_retries = max_retries

    async def start(self, *, task_id: uuid.UUID, agent_id: str, request_id: str) -> bool:
        """返回 True 表示实际启动；False 表示重复/乱序投递，调用方应跳过 handler。"""
        step = await self._get_step(task_id)
        if step.status != "pending":
            logger.warning(
                "任务非 pending 状态，跳过启动",
                task_id=str(task_id),
                status=step.status,
            )
            return False
        now = datetime.now(UTC)
        step.status = "running"
        step.agent_id = agent_id
        step.started_at = now
        step.last_heartbeat_at = now
        self.session.add(
            WorkflowEvent(
                workflow_id=step.workflow_id,
                event_type="task.started",
                payload={"task_id": str(task_id), "agent_id": agent_id},
                request_id=request_id,
            )
        )
        logger.info(
            "任务启动",
            task_id=str(task_id),
            workflow_id=str(step.workflow_id),
            step=step.step,
            attempt=step.attempt,
            agent_id=agent_id,
        )
        return True

    async def complete(self, *, task_id: uuid.UUID, output: dict, request_id: str) -> None:
        step = await self._get_step(task_id)
        if step.status != "running":
            logger.warning(
                "任务非 running 状态，跳过 complete",
                task_id=str(task_id),
                status=step.status,
            )
            return
        now = datetime.now(UTC)
        step.status = "succeeded"
        step.output = output
        step.finished_at = now
        if step.started_at is not None:
            metrics.step_duration_seconds.labels(step=step.step, result="success").observe(
                (now - step.started_at).total_seconds()
            )
        self.session.add(
            WorkflowEvent(
                workflow_id=step.workflow_id,
                event_type="task.succeeded",
                payload={"task_id": str(task_id), "output": output},
                request_id=request_id,
            )
        )
        logger.info(
            "任务执行成功",
            task_id=str(task_id),
            workflow_id=str(step.workflow_id),
            step=step.step,
        )
        await self.session.flush()

        # 从 wf 读 artifact_root，避免 TaskService 与 artifact 路径耦合
        wf = (
            await self.session.execute(select(Workflow).where(Workflow.id == step.workflow_id))
        ).scalar_one()
        wf_service = WorkflowService(self.session, artifact_root=wf.artifact_root)
        await wf_service.advance_on_step_success(step.workflow_id, request_id=request_id)

    async def fail(
        self,
        *,
        task_id: uuid.UUID,
        error: str,
        retryable: bool,
        request_id: str,
    ) -> uuid.UUID | None:
        """失败处理。返回新的 pending task_id（如有重试），或 None（转人工介入）。"""
        step = await self._get_step(task_id)
        if step.status not in ("running", "pending"):
            logger.warning("任务状态异常，无法标记失败", task_id=str(task_id), status=step.status)
            return None
        now = datetime.now(UTC)
        step.status = "failed"
        step.error = error
        step.finished_at = now
        if step.started_at is not None:
            metrics.step_duration_seconds.labels(step=step.step, result="failure").observe(
                (now - step.started_at).total_seconds()
            )
        self.session.add(
            WorkflowEvent(
                workflow_id=step.workflow_id,
                event_type="task.failed",
                payload={
                    "task_id": str(task_id),
                    "error": error,
                    "retryable": retryable,
                },
                request_id=request_id,
            )
        )
        logger.info(
            "任务执行失败",
            task_id=str(task_id),
            workflow_id=str(step.workflow_id),
            step=step.step,
            attempt=step.attempt,
            retryable=retryable,
        )

        if retryable and step.attempt < self.max_retries:
            metrics.step_retries_total.labels(step=step.step).inc()
            return await self._retry(step, request_id=request_id)

        wf = (
            await self.session.execute(select(Workflow).where(Workflow.id == step.workflow_id))
        ).scalar_one()
        src = State(wf.status)
        transition(src, State.AWAITING_MANUAL_ACTION)
        wf.status = State.AWAITING_MANUAL_ACTION.value
        wf.failed_step = step.step
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={
                    "from": src.value,
                    "to": State.AWAITING_MANUAL_ACTION.value,
                },
                request_id=request_id,
            )
        )
        metrics.manual_interventions_total.inc()
        logger.info(
            "工作流转入人工介入",
            workflow_id=str(wf.id),
            failed_step=step.step,
        )
        return None

    async def heartbeat(self, *, task_id: uuid.UUID, message: str | None = None) -> None:
        step = await self._get_step(task_id)
        step.last_heartbeat_at = datetime.now(UTC)
        if message:
            step.heartbeat_message = message

    async def _retry(self, failed: StepExecution, *, request_id: str) -> uuid.UUID:
        new_exec = StepExecution(
            workflow_id=failed.workflow_id,
            step=failed.step,
            attempt=failed.attempt + 1,
            status="pending",
            input=failed.input,
            request_id=request_id,
        )
        self.session.add(new_exec)
        self.session.add(
            WorkflowEvent(
                workflow_id=failed.workflow_id,
                event_type="task.retried",
                payload={
                    "previous_task_id": str(failed.id),
                    "new_task_id": str(new_exec.id),
                    "attempt": new_exec.attempt,
                },
                request_id=request_id,
            )
        )
        await self.session.flush()
        wf = (
            await self.session.execute(select(Workflow).where(Workflow.id == failed.workflow_id))
        ).scalar_one()
        defer_xadd(
            self.session,
            step=failed.step,
            payload={
                "task_id": str(new_exec.id),
                "workflow_id": str(failed.workflow_id),
                "project_name": wf.project_name,
                "step": failed.step,
                "attempt": new_exec.attempt,
                "input": failed.input,
                "artifact_root": wf.artifact_root,
                "request_id": request_id,
            },
        )
        logger.info(
            "任务重试",
            workflow_id=str(failed.workflow_id),
            step=failed.step,
            new_attempt=new_exec.attempt,
        )
        return new_exec.id

    async def _get_step(self, task_id: uuid.UUID) -> StepExecution:
        result = await self.session.execute(
            select(StepExecution).where(StepExecution.id == task_id)
        )
        step = result.scalar_one_or_none()
        if step is None:
            raise ValueError(f"Task {task_id} not found")
        return step
