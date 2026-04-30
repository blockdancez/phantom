"""启动恢复（spec § 4.2E）。

适用场景：DB commit 成功但 XADD 尚未发出时 scheduler 进程崩溃。重启后扫所有
workflow 状态仍在 *_RUNNING 的 pending step_executions，把它们的 XADD payload
重新登记；task_service.start 对非 pending 是幂等 no-op + SDK 见 started=False 会
直接 XACK 跳过，所以即便该 step 已有 in-flight message 也不会重复跑 handler。
"""

from __future__ import annotations

from sqlalchemy import select

from scheduler.observability.logging import get_logger
from scheduler.storage.db import Database, defer_xadd
from scheduler.storage.models import StepExecution, Workflow

logger = get_logger(__name__)


async def run_startup_recovery(database: Database) -> int:
    """扫一次所有需要补 XADD 的 pending step。返回补发的条数。"""
    enqueued = 0
    async with database.session() as session:
        result = await session.execute(
            select(StepExecution, Workflow)
            .join(Workflow, Workflow.id == StepExecution.workflow_id)
            .where(StepExecution.status == "pending")
            .where(Workflow.status.like("%_RUNNING"))
        )
        for step, wf in result.all():
            defer_xadd(
                session,
                step=step.step,
                payload={
                    "task_id": str(step.id),
                    "workflow_id": str(wf.id),
                    "step": step.step,
                    "attempt": step.attempt,
                    "input": step.input,
                    "artifact_root": wf.artifact_root,
                    "request_id": step.request_id,
                },
            )
            enqueued += 1
            logger.info(
                "启动恢复：重新派发任务",
                task_id=str(step.id),
                workflow_id=str(wf.id),
                step=step.step,
                attempt=step.attempt,
            )
    logger.info("启动恢复完成", requeued=enqueued)
    return enqueued
