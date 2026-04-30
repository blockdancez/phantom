"""Agent._run_one 单元测试：验证 handler 成功/重试/致命错误的上报路径。"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aijuicer_sdk import Agent, FatalError, RetryableError


def _payload(tmp_path: Path) -> dict:
    return {
        "task_id": "task-1",
        "workflow_id": "wf-1",
        "step": "idea",
        "attempt": 1,
        "input": {"topic": "hi"},
        "artifact_root": str(tmp_path),
        "request_id": "req_1",
    }


@pytest.mark.asyncio
async def test_run_one_success(tmp_path: Path) -> None:
    agent = Agent(
        name="t",
        step="idea",
        server="http://x",
        redis_url="redis://x",
        configure_logging=False,
    )

    @agent.handler
    async def _h(ctx, task):
        return {"out": 1}

    client = AsyncMock()
    redis_client = AsyncMock()
    agent._agent_id = "agent-uuid"
    sem = asyncio.Semaphore(1)
    await sem.acquire()

    await agent._run_one(
        client=client,
        redis_client=redis_client,
        message_id="0-1",
        payload=_payload(tmp_path),
        sem=sem,
    )

    client.task_start.assert_awaited_once()
    client.task_complete.assert_awaited_once_with(
        task_id="task-1", output={"out": 1}, request_id="req_1"
    )
    client.task_fail.assert_not_awaited()
    redis_client.xack.assert_awaited_once_with("tasks:idea", "agents:idea", "0-1")


@pytest.mark.asyncio
async def test_run_one_retryable_error_flags_retry(tmp_path: Path) -> None:
    agent = Agent(
        name="t",
        step="idea",
        server="http://x",
        redis_url="redis://x",
        configure_logging=False,
    )

    @agent.handler
    async def _h(ctx, task):
        raise RetryableError("llm rate limit")

    client = AsyncMock()
    redis_client = AsyncMock()
    sem = asyncio.Semaphore(1)
    await sem.acquire()

    await agent._run_one(
        client=client,
        redis_client=redis_client,
        message_id="0-2",
        payload=_payload(tmp_path),
        sem=sem,
    )
    client.task_complete.assert_not_awaited()
    client.task_fail.assert_awaited_once()
    kwargs = client.task_fail.await_args.kwargs
    assert kwargs["retryable"] is True
    assert "llm rate limit" in kwargs["error"]
    redis_client.xack.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_one_fatal_error_flags_no_retry(tmp_path: Path) -> None:
    agent = Agent(
        name="t",
        step="idea",
        server="http://x",
        redis_url="redis://x",
        configure_logging=False,
    )

    @agent.handler
    async def _h(ctx, task):
        raise FatalError("bad input")

    client = AsyncMock()
    redis_client = AsyncMock()
    sem = asyncio.Semaphore(1)
    await sem.acquire()

    await agent._run_one(
        client=client,
        redis_client=redis_client,
        message_id="0-3",
        payload=_payload(tmp_path),
        sem=sem,
    )
    client.task_fail.assert_awaited_once()
    assert client.task_fail.await_args.kwargs["retryable"] is False


@pytest.mark.asyncio
async def test_run_one_unexpected_error_defaults_retryable(tmp_path: Path) -> None:
    agent = Agent(
        name="t",
        step="idea",
        server="http://x",
        redis_url="redis://x",
        configure_logging=False,
    )

    @agent.handler
    async def _h(ctx, task):
        raise ValueError("oops")

    client = AsyncMock()
    redis_client = AsyncMock()
    sem = asyncio.Semaphore(1)
    await sem.acquire()

    await agent._run_one(
        client=client,
        redis_client=redis_client,
        message_id="0-4",
        payload=_payload(tmp_path),
        sem=sem,
    )
    client.task_fail.assert_awaited_once()
    kwargs = client.task_fail.await_args.kwargs
    assert kwargs["retryable"] is True
    assert "ValueError" in kwargs["error"]


def test_duplicate_handler_raises() -> None:
    agent = Agent(name="t", step="idea", configure_logging=False)

    @agent.handler
    async def _h1(ctx, task):
        return {}

    with pytest.raises(RuntimeError):

        @agent.handler
        async def _h2(ctx, task):
            return {}
