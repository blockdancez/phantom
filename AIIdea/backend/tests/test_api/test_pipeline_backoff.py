"""Unit tests for the exponential-backoff helper used by per-source collectors.

Feature-1 requires that rate-limited (HTTP 429) or transient network errors
retry with exponential backoff rather than immediately folding to 503.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from src.api import pipeline as pipeline_module


class _StubCollector:
    def __init__(self, plan: list):
        # ``plan`` elements are either an exception to raise or a list of
        # items to return.
        self.plan = list(plan)
        self.calls = 0

    async def collect(self, limit: int = 30):
        self.calls += 1
        step = self.plan.pop(0)
        if isinstance(step, BaseException):
            raise step
        return step

    async def close(self) -> None:
        return None


def _rate_limit_error() -> httpx.HTTPStatusError:
    req = httpx.Request("GET", "https://example.com/")
    return httpx.HTTPStatusError(
        "429", request=req, response=httpx.Response(429, request=req)
    )


@pytest.mark.asyncio
async def test_backoff_retries_on_429_then_succeeds():
    c = _StubCollector([_rate_limit_error(), _rate_limit_error(), [{"url": "u"}]])
    sleep = AsyncMock()
    result = await pipeline_module._collect_with_backoff(
        c,
        job_id="collect_hackernews",
        label="hackernews",
        max_attempts=3,
        base_backoff_seconds=0.01,
        sleep=sleep,
    )
    assert result == [{"url": "u"}]
    assert c.calls == 3
    # Two retries → two backoff sleeps with doubling delays.
    assert sleep.await_count == 2
    delays = [call.args[0] for call in sleep.await_args_list]
    assert delays == [0.01, 0.02]


@pytest.mark.asyncio
async def test_backoff_gives_up_after_max_attempts():
    c = _StubCollector(
        [_rate_limit_error(), _rate_limit_error(), _rate_limit_error()]
    )
    sleep = AsyncMock()
    with pytest.raises(httpx.HTTPStatusError):
        await pipeline_module._collect_with_backoff(
            c,
            job_id="collect_reddit",
            label="reddit",
            max_attempts=3,
            base_backoff_seconds=0.01,
            sleep=sleep,
        )
    assert c.calls == 3


@pytest.mark.asyncio
async def test_non_retriable_error_raises_without_retry():
    c = _StubCollector([ValueError("bad url")])
    sleep = AsyncMock()
    with pytest.raises(ValueError):
        await pipeline_module._collect_with_backoff(
            c,
            job_id="collect_hackernews",
            label="hackernews",
            max_attempts=3,
            base_backoff_seconds=0.01,
            sleep=sleep,
        )
    assert c.calls == 1
    sleep.assert_not_called()


@pytest.mark.asyncio
async def test_timeout_is_treated_as_retriable():
    c = _StubCollector([httpx.ReadTimeout("slow"), [{"url": "u"}]])
    sleep = AsyncMock()
    result = await pipeline_module._collect_with_backoff(
        c,
        job_id="collect_hackernews",
        label="hackernews",
        max_attempts=3,
        base_backoff_seconds=0.01,
        sleep=sleep,
    )
    assert result == [{"url": "u"}]
    assert sleep.await_count == 1


def test_is_rate_limited_matrix():
    assert pipeline_module._is_rate_limited(_rate_limit_error()) is True
    req = httpx.Request("GET", "https://example.com/")
    not_rate = httpx.HTTPStatusError(
        "404", request=req, response=httpx.Response(404, request=req)
    )
    assert pipeline_module._is_rate_limited(not_rate) is False
    assert pipeline_module._is_rate_limited(httpx.ReadTimeout("x")) is True
    assert pipeline_module._is_rate_limited(httpx.ConnectError("x")) is True
    assert pipeline_module._is_rate_limited(ValueError("x")) is False


def test_scheduled_running_lock_helpers():
    pipeline_module._running_scheduled.clear()
    assert pipeline_module.mark_scheduled_running("collect_data") is True
    assert pipeline_module.is_scheduled_running("collect_data") is True
    # Second call while still running must refuse.
    assert pipeline_module.mark_scheduled_running("collect_data") is False
    pipeline_module.clear_scheduled_running("collect_data")
    assert pipeline_module.is_scheduled_running("collect_data") is False
    # Clearing an id that was never running is a no-op.
    pipeline_module.clear_scheduled_running("never_ran")
