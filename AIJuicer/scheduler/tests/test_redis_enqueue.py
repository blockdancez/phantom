"""验证 DB commit 后 XADD 被真正触发（spec § 3.4 at-least-once 保证）。"""

from __future__ import annotations

import pytest
from sqlalchemy import select

from scheduler.engine.approval_service import ApprovalService
from scheduler.engine.task_service import TaskService
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.db import Database
from scheduler.storage.models import StepExecution
from scheduler.storage.redis_queue import InMemoryTaskQueue


@pytest.mark.asyncio
async def test_create_workflow_enqueues_finder_task(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    async with database.session() as s:
        svc = WorkflowService(s, artifact_root="/tmp/aijuicer-test")
        wf_id = await svc.create(
            name="wf_enqueue",
            project_name="wf-enqueue",
            input={"topic": "t1"},
            approval_policy={},
            request_id="req_enqtest",
        )

    assert len(task_queue.enqueued) == 1
    step, payload = task_queue.enqueued[0]
    assert step == "idea"
    assert payload["workflow_id"] == str(wf_id)
    assert payload["step"] == "idea"
    assert payload["attempt"] == 1
    assert payload["input"] == {"topic": "t1"}
    assert payload["request_id"] == "req_enqtest"
    assert payload["artifact_root"].endswith(str(wf_id))


@pytest.mark.asyncio
async def test_rollback_discards_pending_xadd(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    """事务抛异常 → rollback → 即使 service 登记过 XADD 也不入队。"""
    with pytest.raises(RuntimeError):
        async with database.session() as s:
            svc = WorkflowService(s, artifact_root="/tmp/aijuicer-test")
            await svc.create(
                name="wf_rollback",
                project_name="wf-rollback",
                input={},
                approval_policy={},
                request_id="req_rb",
            )
            raise RuntimeError("simulate failure after service call")

    assert task_queue.enqueued == []


@pytest.mark.asyncio
async def test_complete_auto_policy_enqueues_next_step(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    """policy=auto 时 complete 驱动到下一步 → 队列多一条该步任务。"""
    async with database.session() as s:
        wf_svc = WorkflowService(s, artifact_root="/tmp/aijuicer-test")
        wf_id = await wf_svc.create(
            name="wf_chain",
            project_name="wf-chain",
            input={},
            approval_policy={"requirement": "auto"},
            request_id="req_chain",
        )
    # 第一步 XADD（finder）
    task_queue.enqueued.clear()

    async with database.session() as s:
        task_id = (
            await s.execute(
                select(StepExecution.id)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.step == "idea")
            )
        ).scalar_one()
    async with database.session() as s:
        svc = TaskService(s)
        await svc.start(task_id=task_id, agent_id="a1", request_id="req_chain")
    async with database.session() as s:
        svc = TaskService(s)
        await svc.complete(task_id=task_id, output={"idea": "x"}, request_id="req_chain")

    steps_enqueued = [s for s, _ in task_queue.enqueued]
    assert "requirement" in steps_enqueued


@pytest.mark.asyncio
async def test_approval_approve_enqueues_next_step(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    """AWAITING_APPROVAL_REQUIREMENT --approve--> REQUIREMENT_RUNNING，入队一条。"""
    async with database.session() as s:
        wf_svc = WorkflowService(s, artifact_root="/tmp/aijuicer-test")
        wf_id = await wf_svc.create(
            name="wf_apv",
            project_name="wf-apv",
            input={},
            approval_policy={},  # 默认 manual
            request_id="req_apv",
        )
    task_queue.enqueued.clear()

    async with database.session() as s:
        task_id = (
            await s.execute(
                select(StepExecution.id)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.step == "idea")
            )
        ).scalar_one()
    async with database.session() as s:
        await TaskService(s).start(task_id=task_id, agent_id="a1", request_id="req_apv")
    async with database.session() as s:
        await TaskService(s).complete(task_id=task_id, output={"idea": "x"}, request_id="req_apv")
    # complete 后应该停在 AWAITING_APPROVAL_REQUIREMENT，无新 enqueue
    task_queue.enqueued.clear()

    async with database.session() as s:
        await ApprovalService(s).approve(
            workflow_id=wf_id,
            step="requirement",
            comment=None,
            request_id="req_apv",
        )

    assert len(task_queue.enqueued) == 1
    step, payload = task_queue.enqueued[0]
    assert step == "requirement"
    assert payload["step"] == "requirement"
    assert payload["workflow_id"] == str(wf_id)
