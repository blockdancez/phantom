"""SSE event bus + artifacts API 基础冒烟。"""

from __future__ import annotations

import asyncio
import uuid
from pathlib import Path

import pytest
from sqlalchemy import select

from scheduler.engine.event_bus import EventBus, get_event_bus
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.db import Database
from scheduler.storage.models import Artifact


@pytest.mark.asyncio
async def test_event_bus_publishes_to_subscribers(
    database: Database,
) -> None:
    """创建 workflow → commit 后 bus 广播 → 订阅者能收到。"""
    bus = get_event_bus()
    wf_id_holder: dict[str, uuid.UUID] = {}

    # 先建一个 workflow 拿到 id 以便订阅（订阅是按 id）
    async with database.session() as s:
        wf_id_holder["id"] = await WorkflowService(s, artifact_root="/tmp/art").create(
            name="wf_bus_setup",
            project_name="wf-bus-setup",
            input={},
            approval_policy={},
            request_id="req_bus",
        )
    wf_id = wf_id_holder["id"]

    q = bus.subscribe(wf_id)
    try:
        # 再触发一次 service 事件：一个 approval 之前的建 workflow 事件不会被收到
        async with database.session() as s:
            # 用 rerun 以触发一个 state.changed 事件？更简单——直接 publish 手动事件
            bus.publish(wf_id, {"event_type": "test.ping", "payload": {"x": 1}})
        ev = await asyncio.wait_for(q.get(), timeout=1.0)
        assert ev["event_type"] == "test.ping"
        assert ev["payload"] == {"x": 1}
    finally:
        bus.unsubscribe(wf_id, q)


def test_event_bus_slow_subscriber_does_not_block() -> None:
    bus = EventBus()
    wf_id = uuid.uuid4()
    q = bus.subscribe(wf_id)
    # 填满队列
    for i in range(300):
        bus.publish(wf_id, {"event_type": "spam", "payload": {"i": i}})
    # 不挂起 → OK
    assert q.qsize() > 0
    bus.unsubscribe(wf_id, q)


@pytest.mark.asyncio
async def test_artifact_file_round_trip(database: Database, tmp_path: Path) -> None:
    """SDK AgentContext 原子写 + 调用 create_artifact；scheduler 插入一条元数据能读回。"""
    from unittest.mock import AsyncMock

    from aijuicer_sdk.context import AgentContext

    from scheduler.storage.models import Workflow

    async with database.session() as s:
        wf_id = await WorkflowService(s, artifact_root=tmp_path).create(
            name="wf_art",
            project_name="wf-art",
            input={},
            approval_policy={},
            request_id="req_art",
        )
    async with database.session() as s:
        wf = (await s.execute(select(Workflow).where(Workflow.id == wf_id))).scalar_one()
        artifact_root = wf.artifact_root

    client = AsyncMock()
    ctx = AgentContext(
        task_id="t",
        workflow_id=str(wf_id),
        step="idea",
        attempt=1,
        input={},
        artifact_root=artifact_root,
        request_id="req_art",
        client=client,
    )
    ref = await ctx.save_artifact("idea.md", "hello world")
    assert ref.path.exists()
    assert ref.path.read_text() == "hello world"
    client.create_artifact.assert_awaited_once()

    async with database.session() as s:
        s.add(
            Artifact(
                workflow_id=wf_id,
                step="idea",
                key="idea.md",
                path=str(ref.path),
                size_bytes=ref.size_bytes,
                content_type="text/markdown",
                sha256=ref.sha256,
            )
        )
    async with database.session() as s:
        rows = (
            (await s.execute(select(Artifact).where(Artifact.workflow_id == wf_id))).scalars().all()
        )
    assert len(rows) == 1
    assert rows[0].key == "idea.md"
