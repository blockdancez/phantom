import uuid

import pytest
from sqlalchemy import select

from scheduler.engine.state_machine import State
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent


@pytest.mark.asyncio
async def test_create_workflow_initializes_state_and_enqueues_first_step(db_session):
    service = WorkflowService(db_session, artifact_root="/tmp/art")
    wf_id = await service.create(
        name="test-wf",
        project_name="test-wf",
        input={"topic": "video"},
        approval_policy={"requirement": "auto"},
        request_id="req_test1",
    )

    wf = (await db_session.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
    assert wf.name == "test-wf"
    assert wf.status == State.IDEA_RUNNING.value
    assert wf.current_step == "idea"
    assert wf.artifact_root.endswith(str(wf_id))

    step = (
        await db_session.execute(select(StepExecution).where(StepExecution.workflow_id == wf_id))
    ).scalar_one()
    assert step.step == "idea"
    assert step.attempt == 1
    assert step.status == "pending"
    assert step.request_id == "req_test1"

    events = (
        (
            await db_session.execute(
                select(WorkflowEvent)
                .where(WorkflowEvent.workflow_id == wf_id)
                .order_by(WorkflowEvent.id)
            )
        )
        .scalars()
        .all()
    )
    assert [e.event_type for e in events] == [
        "workflow.created",
        "state.changed",
        "task.enqueued",
    ]


@pytest.mark.asyncio
async def test_get_returns_none_for_unknown(db_session):
    service = WorkflowService(db_session, artifact_root="/tmp/art")
    result = await service.get(uuid.uuid4())
    assert result is None


@pytest.mark.asyncio
async def test_list_filters_by_status(db_session):
    service = WorkflowService(db_session, artifact_root="/tmp/art")
    id1 = await service.create(
        name="a", project_name="a", input={}, approval_policy={}, request_id="r1"
    )
    id2 = await service.create(
        name="b", project_name="b", input={}, approval_policy={}, request_id="r2"
    )

    all_wf = await service.list()
    assert len(all_wf) >= 2

    running = await service.list(status=State.IDEA_RUNNING.value)
    ids = [w.id for w in running]
    assert id1 in ids and id2 in ids
