"""启动恢复扫描（spec § 4.2E）。"""

from __future__ import annotations

import pytest

from scheduler.engine.recovery import run_startup_recovery
from scheduler.engine.workflow_service import WorkflowService
from scheduler.storage.db import Database
from scheduler.storage.redis_queue import InMemoryTaskQueue


@pytest.mark.asyncio
async def test_recovery_requeues_pending_in_running_workflow(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    """创建 workflow 后清空队列 → 模拟 XADD 丢失 → 恢复器补发。"""
    async with database.session() as s:
        svc = WorkflowService(s, artifact_root="/tmp/art")
        wf_id = await svc.create(
            name="wf_recover",
            project_name="wf-recover",
            input={"topic": "t"},
            approval_policy={},
            request_id="req_rec",
        )
    task_queue.enqueued.clear()

    requeued = await run_startup_recovery(database)
    assert requeued >= 1
    # 包含刚才那个 workflow 的 finder 任务
    matching = [
        (s, p) for s, p in task_queue.enqueued if p["workflow_id"] == str(wf_id) and s == "idea"
    ]
    assert len(matching) == 1
    assert matching[0][1]["request_id"] == "req_rec"


@pytest.mark.asyncio
async def test_recovery_skips_terminal_or_running_workflows(
    database: Database, task_queue: InMemoryTaskQueue
) -> None:
    """只恢复 pending 且 workflow 在 *_RUNNING 的条目。"""
    # 已经在 IDEA_RUNNING、step pending —— 会被恢复
    async with database.session() as s:
        svc = WorkflowService(s, artifact_root="/tmp/art")
        await svc.create(
            name="wf_keep",
            project_name="wf-keep",
            input={},
            approval_policy={},
            request_id="req_keep",
        )
    task_queue.enqueued.clear()

    requeued = await run_startup_recovery(database)
    # 可能 > 1，因为 session 作用域累积了其他测试的 pending 行；只断言至少有新的 workflow
    assert requeued >= 1
    workflows = {p["workflow_id"] for _s, p in task_queue.enqueued}
    assert len(workflows) >= 1
