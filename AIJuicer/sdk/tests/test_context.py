"""AgentContext：原子写入、sha256、load_artifact 读回。"""

from __future__ import annotations

import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aijuicer_sdk.context import AgentContext


def _make_ctx(tmp_path: Path, *, step: str = "idea") -> AgentContext:
    client = AsyncMock()
    return AgentContext(
        task_id="t1",
        workflow_id="wf1",
        step=step,
        attempt=1,
        input={"topic": "x"},
        artifact_root=str(tmp_path),
        request_id="req_test",
        client=client,
    )


@pytest.mark.asyncio
async def test_save_artifact_writes_atomically(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    ref = await ctx.save_artifact("idea.md", "hello world")

    assert ref.path.exists()
    assert ref.path.read_text() == "hello world"
    assert ref.size_bytes == len(b"hello world")
    assert ref.sha256 == hashlib.sha256(b"hello world").hexdigest()
    # 没有遗留的 .tmp
    leftover = list(ref.path.parent.glob("*.tmp"))
    assert leftover == []


@pytest.mark.asyncio
async def test_save_artifact_bytes_and_step_dir_layout(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, step="design")
    ref = await ctx.save_artifact("wireframe.bin", b"\x00\x01\x02")
    assert ref.path.parent.name == "04_design"
    assert ref.path.read_bytes() == b"\x00\x01\x02"


@pytest.mark.asyncio
async def test_load_artifact_roundtrip(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path, step="idea")
    await ctx.save_artifact("idea.md", "roundtrip")
    # 跨 step 读取也走同一 artifact_root / <step_dir> 映射
    data = ctx.load_artifact("idea", "idea.md")
    assert data == b"roundtrip"


@pytest.mark.asyncio
async def test_heartbeat_proxies_to_client(tmp_path: Path) -> None:
    ctx = _make_ctx(tmp_path)
    await ctx.heartbeat("progress 50%")
    ctx._client.task_heartbeat.assert_awaited_once_with(
        task_id="t1", message="progress 50%", request_id="req_test"
    )


def test_from_task_payload_parses_fields(tmp_path: Path) -> None:
    payload = {
        "task_id": "t-42",
        "workflow_id": "wf-42",
        "step": "plan",
        "attempt": 2,
        "input": {"k": "v"},
        "artifact_root": str(tmp_path),
        "request_id": "req_xyz",
    }
    client = AsyncMock()
    ctx = AgentContext.from_task_payload(payload, client=client)
    assert ctx.task_id == "t-42"
    assert ctx.attempt == 2
    assert ctx.step == "plan"
    assert ctx.request_id == "req_xyz"
