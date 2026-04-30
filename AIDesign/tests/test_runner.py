"""runner.py 单测。"""
from __future__ import annotations

from pathlib import Path

import pytest

from ai_design.runner import (
    PROJECTS_BASE_DEFAULT,
    resolve_workspace,
    workspace_has_phantom_state,
)


def test_resolve_workspace_joins_base_and_project_name(tmp_workspace_base: Path) -> None:
    """工作区 = PHANTOM_PROJECTS_BASE / project_name，幂等创建。"""
    result = resolve_workspace("todo-app")
    assert result == tmp_workspace_base / "todo-app"
    assert result.is_dir()


def test_resolve_workspace_idempotent_when_dir_exists(tmp_workspace_base: Path) -> None:
    """目录已存在（idea/requirement step 创建过）也应返回成功，不报错。"""
    (tmp_workspace_base / "existing").mkdir()
    (tmp_workspace_base / "existing" / "requirement.md").write_text("# req")
    result = resolve_workspace("existing")
    assert result == tmp_workspace_base / "existing"
    assert (result / "requirement.md").read_text() == "# req"  # 已有内容不被破坏


def test_resolve_workspace_rejects_empty_project_name() -> None:
    with pytest.raises(ValueError, match="project_name"):
        resolve_workspace("")


def test_resolve_workspace_rejects_unsafe_project_name(tmp_workspace_base: Path) -> None:
    """防止 ../ 逃逸到 base 之外。"""
    with pytest.raises(ValueError, match="project_name"):
        resolve_workspace("../../etc")
    with pytest.raises(ValueError, match="project_name"):
        resolve_workspace("/abs/path")


def test_default_base_is_user_phantom_dir() -> None:
    """没设环境变量时，默认 base 是 /Users/lapsdoor/phantom。"""
    assert PROJECTS_BASE_DEFAULT == Path("/Users/lapsdoor/phantom")


def test_workspace_has_phantom_state_false_when_empty(tmp_workspace_base: Path) -> None:
    ws = resolve_workspace("p")
    assert workspace_has_phantom_state(ws) is False


def test_workspace_has_phantom_state_true_when_state_json_exists(
    tmp_workspace_base: Path,
) -> None:
    ws = resolve_workspace("p")
    (ws / ".phantom").mkdir()
    (ws / ".phantom" / "state.json").write_text("{}")
    assert workspace_has_phantom_state(ws) is True


import os
from unittest.mock import AsyncMock

import pytest

from ai_design.runner import (
    PhantomFailedError,
    run_phantom,
)


@pytest.mark.asyncio
async def test_run_phantom_success_streams_heartbeat(tmp_path: Path, monkeypatch) -> None:
    """phantom 成功退出（rc=0），每行 stdout 都通过 heartbeat 上报。"""
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    heartbeat = AsyncMock()
    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan", "test.md"],
        heartbeat=heartbeat,
        phantom_bin=str(fake),
    )
    assert rc == 0
    # 至少 3 行 stdout（starting / doing work / done）都触发了心跳
    assert heartbeat.await_count >= 3
    # 心跳消息包含 phantom 的输出
    call_messages = [c.args[0] for c in heartbeat.await_args_list]
    assert any("starting" in m for m in call_messages)
    assert any("done" in m for m in call_messages)


@pytest.mark.asyncio
async def test_run_phantom_runs_in_workspace_cwd(tmp_path: Path) -> None:
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    captured_cwd: list[str] = []

    async def capture_cwd(msg: str) -> None:
        if msg.startswith("FAKE_PHANTOM_CWD:"):
            captured_cwd.append(msg.split(":", 1)[1].strip())

    # heartbeat 收 stdout 行（fake 里 cwd 是 stderr，下面用 stderr_callback）
    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan"],
        heartbeat=AsyncMock(),
        phantom_bin=str(fake),
        stderr_callback=capture_cwd,
    )
    assert rc == 0
    assert captured_cwd == [str(tmp_path)]


@pytest.mark.asyncio
async def test_run_phantom_passes_args_through(tmp_path: Path) -> None:
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    captured: list[str] = []

    async def capture_args(msg: str) -> None:
        if msg.startswith("FAKE_PHANTOM_ARGS:"):
            captured.append(msg.split(":", 1)[1].strip())

    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan", "增加搜索功能"],
        heartbeat=AsyncMock(),
        phantom_bin=str(fake),
        stderr_callback=capture_args,
    )
    assert rc == 0
    assert captured == ["--plan 增加搜索功能"]


@pytest.mark.asyncio
async def test_run_phantom_nonzero_exit_raises(tmp_path: Path, monkeypatch) -> None:
    fake = Path(__file__).parent / "fakes" / "fake_phantom.sh"
    monkeypatch.setenv("FAKE_PHANTOM_EXIT", "7")
    with pytest.raises(PhantomFailedError) as ei:
        await run_phantom(
            workspace=tmp_path,
            args=["--plan"],
            heartbeat=AsyncMock(),
            phantom_bin=str(fake),
        )
    assert ei.value.exit_code == 7
    assert "phantom" in str(ei.value).lower()


@pytest.mark.asyncio
async def test_run_phantom_inherits_env(tmp_path: Path, monkeypatch) -> None:
    """PHANTOM_*_BACKEND 环境变量必须透传给子进程。"""
    fake_path = Path(__file__).parent / "fakes" / "fake_phantom_env.sh"
    fake_path.write_text(
        "#!/usr/bin/env bash\n"
        "echo \"BACKEND=${PHANTOM_GENERATOR_BACKEND:-unset}\" >&2\n"
        "exit 0\n"
    )
    fake_path.chmod(0o755)

    monkeypatch.setenv("PHANTOM_GENERATOR_BACKEND", "codex")
    captured: list[str] = []

    async def capture(msg: str) -> None:
        if msg.startswith("BACKEND="):
            captured.append(msg)

    rc = await run_phantom(
        workspace=tmp_path,
        args=["--plan"],
        heartbeat=AsyncMock(),
        phantom_bin=str(fake_path),
        stderr_callback=capture,
    )
    assert rc == 0
    assert captured == ["BACKEND=codex"]


from aijuicer_sdk import FatalError, RetryableError

from ai_design.runner import classify_phantom_failure


def test_classify_timeout_is_retryable() -> None:
    err = PhantomFailedError(124, ["AI 调用超时（1800s），role=generator"])
    out = classify_phantom_failure(err)
    assert isinstance(out, RetryableError)
    assert "1800s" in str(out)


def test_classify_rate_limit_is_retryable() -> None:
    err = PhantomFailedError(1, ["LLM rate limited: try again"])
    assert isinstance(classify_phantom_failure(err), RetryableError)


def test_classify_connection_error_is_retryable() -> None:
    err = PhantomFailedError(1, ["Connection refused", "exiting"])
    assert isinstance(classify_phantom_failure(err), RetryableError)


def test_classify_missing_plan_is_fatal() -> None:
    err = PhantomFailedError(1, ["design 模式需要 .phantom/plan.locked.md 已存在"])
    out = classify_phantom_failure(err)
    assert isinstance(out, FatalError)


def test_classify_max_rounds_is_fatal() -> None:
    err = PhantomFailedError(1, ["group g-1 达到 max_rounds=6 仍未通过（strict 模式）"])
    assert isinstance(classify_phantom_failure(err), FatalError)


def test_classify_unknown_failure_defaults_retryable() -> None:
    err = PhantomFailedError(1, ["something weird went wrong"])
    out = classify_phantom_failure(err)
    assert isinstance(out, RetryableError)
