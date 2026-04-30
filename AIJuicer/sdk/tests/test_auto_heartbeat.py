"""SDK 自动心跳：handler 执行期间每 interval 秒上报一次。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aijuicer_sdk import Agent


def _payload(tmp_path: Path) -> dict:
    return {
        "task_id": "task-hb",
        "workflow_id": "wf-hb",
        "step": "idea",
        "attempt": 1,
        "input": {},
        "artifact_root": str(tmp_path),
        "request_id": "req_hb",
    }


@pytest.mark.asyncio
async def test_auto_heartbeat_fires_during_handler(tmp_path: Path) -> None:
    """handler sleep 比 heartbeat_interval 久 → 至少触发一次。"""
    agent = Agent(
        name="t",
        step="idea",
        server="http://x",
        redis_url="redis://x",
        heartbeat_interval=0.05,
        configure_logging=False,
    )

    @agent.handler
    async def _h(ctx, task):
        await asyncio.sleep(0.2)
        return {}

    client = AsyncMock()
    client.task_start.return_value = {"ok": True, "started": True}
    redis_client = AsyncMock()
    sem = asyncio.Semaphore(1)
    await sem.acquire()

    await agent._run_one(
        client=client,
        redis_client=redis_client,
        message_id="0-hb",
        payload=_payload(tmp_path),
        sem=sem,
    )
    assert client.task_heartbeat.await_count >= 1
    client.task_complete.assert_awaited_once()


@pytest.mark.asyncio
async def test_start_not_started_skips_handler(tmp_path: Path) -> None:
    """scheduler 回 started=False → 不调 handler，只 XACK。"""
    agent = Agent(
        name="t",
        step="idea",
        server="http://x",
        redis_url="redis://x",
        configure_logging=False,
    )

    called = False

    @agent.handler
    async def _h(ctx, task):
        nonlocal called
        called = True
        return {}

    client = AsyncMock()
    client.task_start.return_value = {"ok": True, "started": False}
    redis_client = AsyncMock()
    sem = asyncio.Semaphore(1)
    await sem.acquire()

    await agent._run_one(
        client=client,
        redis_client=redis_client,
        message_id="0-dup",
        payload=_payload(tmp_path),
        sem=sem,
    )
    assert called is False
    client.task_complete.assert_not_awaited()
    client.task_fail.assert_not_awaited()
    redis_client.xack.assert_awaited_once()
