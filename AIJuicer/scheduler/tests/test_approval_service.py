import uuid

import pytest
from sqlalchemy import select

from scheduler.engine.approval_service import ApprovalService
from scheduler.engine.state_machine import State
from scheduler.engine.task_service import TaskService
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.models import Approval, StepExecution, Workflow


async def _create_and_finish_first_step(
    db_session, *, approval_policy: dict
) -> tuple[uuid.UUID, uuid.UUID]:
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t",
        project_name="t",
        input={"topic": "x"},
        approval_policy=approval_policy,
        request_id="req_c",
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()
    ts = TaskService(db_session)
    await ts.start(task_id=task_id, agent_id="a1", request_id="r")
    await ts.complete(task_id=task_id, output={}, request_id="r")
    return wf_id, task_id


@pytest.mark.asyncio
async def test_approve_advances_from_awaiting_approval(db_session):
    wf_id, _ = await _create_and_finish_first_step(
        db_session, approval_policy={"requirement": "manual"}
    )
    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.AWAITING_APPROVAL_REQUIREMENT.value

    svc = ApprovalService(db_session)
    await svc.approve(workflow_id=wf_id, step="requirement", comment="ok", request_id="r2")

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.REQUIREMENT_RUNNING.value

    record = (
        await db_session.execute(select(Approval).where(Approval.workflow_id == wf_id))
    ).scalar_one()
    assert record.decision == "approve"
    assert record.step == "requirement"
    assert record.comment == "ok"


@pytest.mark.asyncio
async def test_reject_aborts_workflow(db_session):
    wf_id, _ = await _create_and_finish_first_step(
        db_session, approval_policy={"requirement": "manual"}
    )
    svc = ApprovalService(db_session)
    await svc.reject(workflow_id=wf_id, step="requirement", comment="bad", request_id="r2")

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.ABORTED.value


@pytest.mark.asyncio
async def test_abort_any_state(db_session):
    wf_id, _ = await _create_and_finish_first_step(
        db_session, approval_policy={"requirement": "auto"}
    )
    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.REQUIREMENT_RUNNING.value

    svc = ApprovalService(db_session)
    await svc.abort(workflow_id=wf_id, comment="stop", request_id="r2")

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.ABORTED.value


@pytest.mark.asyncio
async def test_rerun_from_manual_action(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="r"
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()
    ts = TaskService(db_session)
    await ts.start(task_id=task_id, agent_id="a", request_id="r")
    await ts.fail(task_id=task_id, error="x", retryable=False, request_id="r")

    svc = ApprovalService(db_session)
    new_task_id = await svc.rerun(
        workflow_id=wf_id,
        step="idea",
        modified_input=None,
        comment="retry",
        request_id="r2",
    )
    assert new_task_id is not None

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.IDEA_RUNNING.value

    new_step = (
        await db_session.execute(select(StepExecution).where(StepExecution.id == new_task_id))
    ).scalar_one()
    assert new_step.status == "pending"
    assert new_step.step == "idea"


@pytest.mark.asyncio
async def test_skip_from_manual_action_goes_to_next_awaiting_approval(db_session):
    """finder 失败后 skip，应推进到 AWAITING_APPROVAL_REQUIREMENT（默认 manual policy）。"""
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="r"
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()
    ts = TaskService(db_session)
    await ts.start(task_id=task_id, agent_id="a", request_id="r")
    await ts.fail(task_id=task_id, error="x", retryable=False, request_id="r")

    # 进入 AWAITING_MANUAL_ACTION
    svc = ApprovalService(db_session)
    await svc.skip(workflow_id=wf_id, comment="skip finder", request_id="r2")

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.AWAITING_APPROVAL_REQUIREMENT.value
    assert wf.failed_step is None


@pytest.mark.asyncio
async def test_skip_rejects_when_not_in_manual_action(db_session):
    """非 AWAITING_MANUAL_ACTION 状态调 skip 应抛 ValueError。"""
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="r"
    )

    svc = ApprovalService(db_session)
    with pytest.raises(ValueError):
        await svc.skip(workflow_id=wf_id, comment="", request_id="r2")
