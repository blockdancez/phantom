import pytest
from sqlalchemy import select

from scheduler.engine.state_machine import State
from scheduler.engine.task_service import TaskService
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.models import StepExecution, Workflow


@pytest.mark.asyncio
async def test_start_task_sets_running(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()

    task_service = TaskService(db_session)
    await task_service.start(task_id=task_id, agent_id="agent-01", request_id="req_2")

    step = (
        await db_session.execute(select(StepExecution).where(StepExecution.id == task_id))
    ).scalar_one()
    assert step.status == "running"
    assert step.agent_id == "agent-01"
    assert step.started_at is not None
    assert step.last_heartbeat_at is not None


@pytest.mark.asyncio
async def test_complete_task_marks_succeeded_and_advances_workflow(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t",
        project_name="t",
        input={},
        approval_policy={"requirement": "auto"},
        request_id="req_1",
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()

    task_service = TaskService(db_session)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    await task_service.complete(task_id=task_id, output={"idea_summary": "..."}, request_id="r3")

    step = (
        await db_session.execute(select(StepExecution).where(StepExecution.id == task_id))
    ).scalar_one()
    assert step.status == "succeeded"
    assert step.output == {"idea_summary": "..."}

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.REQUIREMENT_RUNNING.value


@pytest.mark.asyncio
async def test_fail_task_retryable_creates_new_attempt(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()

    task_service = TaskService(db_session, max_retries=3)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    new_task_id = await task_service.fail(
        task_id=task_id, error="boom", retryable=True, request_id="r3"
    )

    assert new_task_id is not None and new_task_id != task_id

    step1 = (
        await db_session.execute(select(StepExecution).where(StepExecution.id == task_id))
    ).scalar_one()
    assert step1.status == "failed"

    step2 = (
        await db_session.execute(select(StepExecution).where(StepExecution.id == new_task_id))
    ).scalar_one()
    assert step2.attempt == 2
    assert step2.status == "pending"
    assert step2.step == "idea"


@pytest.mark.asyncio
async def test_fail_task_fatal_goes_to_manual_action(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()

    task_service = TaskService(db_session, max_retries=3)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    new_task_id = await task_service.fail(
        task_id=task_id, error="fatal", retryable=False, request_id="r3"
    )

    assert new_task_id is None

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.AWAITING_MANUAL_ACTION.value
    assert wf.failed_step == "idea"


@pytest.mark.asyncio
async def test_fail_task_retry_exhausted_goes_to_manual_action(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_service = TaskService(db_session, max_retries=2)

    for attempt in range(2):
        task_id = (
            await db_session.execute(
                select(StepExecution.id)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.attempt == attempt + 1)
            )
        ).scalar_one()
        await task_service.start(task_id=task_id, agent_id="a1", request_id="r")
        new_id = await task_service.fail(
            task_id=task_id, error="boom", retryable=True, request_id="r"
        )
        if attempt == 0:
            assert new_id is not None
        else:
            assert new_id is None

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.status == State.AWAITING_MANUAL_ACTION.value


@pytest.mark.asyncio
async def test_heartbeat_updates_timestamp(db_session):
    wf_service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await wf_service.create(
        name="t", project_name="t", input={}, approval_policy={}, request_id="req_1"
    )
    task_id = (
        await db_session.execute(select(StepExecution.id).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()

    task_service = TaskService(db_session)
    await task_service.start(task_id=task_id, agent_id="a1", request_id="r2")
    before = (
        await db_session.execute(
            select(StepExecution.last_heartbeat_at).where(StepExecution.id == task_id)
        )
    ).scalar_one()

    await task_service.heartbeat(task_id=task_id, message="working on LLM call")

    after = (
        await db_session.execute(
            select(StepExecution.last_heartbeat_at).where(StepExecution.id == task_id)
        )
    ).scalar_one()
    assert after >= before
    msg = (
        await db_session.execute(
            select(StepExecution.heartbeat_message).where(StepExecution.id == task_id)
        )
    ).scalar_one()
    assert msg == "working on LLM call"
