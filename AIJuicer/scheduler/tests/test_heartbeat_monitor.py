"""心跳超时监控（spec § 4.2D）。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select

from scheduler.engine.state_machine import State
from scheduler.engine.task_service import TaskService
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.db import Database
from scheduler.storage.models import StepExecution, Workflow
from scheduler.storage.redis_queue import InMemoryTaskQueue
from scheduler.workers.heartbeat_monitor import scan_once


async def _create_running_step(database: Database) -> StepExecution:
    async with database.session() as s:
        svc = WorkflowService(s, artifact_root="/tmp/art")
        wf_id = await svc.create(
            name="wf_hb",
            project_name="wf-hb",
            input={},
            approval_policy={},
            request_id="req_hb",
        )
    async with database.session() as s:
        step = (
            await s.execute(
                select(StepExecution)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.step == "idea")
            )
        ).scalar_one()
        tid = step.id
    async with database.session() as s:
        await TaskService(s).start(task_id=tid, agent_id="a", request_id="req_hb")
    # 取最新状态
    async with database.session() as s:
        return (await s.execute(select(StepExecution).where(StepExecution.id == tid))).scalar_one()


@pytest.mark.asyncio
async def test_scan_once_times_out_stale_step_and_retries(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    step = await _create_running_step(database)
    # 手动把 last_heartbeat_at 调老
    async with database.session() as s:
        s_obj = (
            await s.execute(select(StepExecution).where(StepExecution.id == step.id))
        ).scalar_one()
        s_obj.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=300)
    task_queue.enqueued.clear()

    timed = await scan_once(database, timeout_sec=90, max_retries=3)
    assert timed >= 1  # 共享 DB，其他测试可能留下 stale；这里只关心至少有我们这条

    # 该 step 已 failed，新 attempt pending + 入队一条 finder
    async with database.session() as s:
        rows = (
            (
                await s.execute(
                    select(StepExecution)
                    .where(StepExecution.workflow_id == step.workflow_id)
                    .order_by(StepExecution.attempt)
                )
            )
            .scalars()
            .all()
        )
    assert [r.status for r in rows] == ["failed", "pending"]
    assert rows[1].attempt == 2
    assert any(s == "idea" for s, _ in task_queue.enqueued)


@pytest.mark.asyncio
async def test_scan_once_exhausted_retries_goes_to_manual_action(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    """max_retries=1 时直接进入 AWAITING_MANUAL_ACTION。"""
    step = await _create_running_step(database)
    async with database.session() as s:
        s_obj = (
            await s.execute(select(StepExecution).where(StepExecution.id == step.id))
        ).scalar_one()
        s_obj.last_heartbeat_at = datetime.now(UTC) - timedelta(seconds=300)
    task_queue.enqueued.clear()

    timed = await scan_once(database, timeout_sec=90, max_retries=1)
    assert timed == 1

    async with database.session() as s:
        wf = (await s.execute(select(Workflow).where(Workflow.id == step.workflow_id))).scalar_one()
    assert wf.status == State.AWAITING_MANUAL_ACTION.value
    assert wf.failed_step == "idea"


@pytest.mark.asyncio
async def test_scan_once_ignores_fresh_heartbeat(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    await _create_running_step(database)
    task_queue.enqueued.clear()
    timed = await scan_once(database, timeout_sec=90, max_retries=3)
    assert timed == 0
    assert task_queue.enqueued == []
