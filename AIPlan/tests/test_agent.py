"""ai_plan.py 单测：mock phantom 子进程，断言参数 / 产物。"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aijuicer_sdk import FatalError, RetryableError

from ai_plan.agent import handle


PROJECT = "todo-test"


def _make_ctx(
    attempt: int = 1,
    with_requirement: bool = True,
    feedback: str | None = None,
    project_name: str = PROJECT,
):
    """构造 mock AgentContext（aijuicer-sdk 0.6+ 单参 handler，所有字段挂在 ctx 上）。"""
    inp: dict = {"text": "build a todo app"}
    if feedback is not None:
        inp["user_feedback"] = {"plan": feedback}
    ctx = AsyncMock()
    ctx.workflow_id = "wf-test-123"
    ctx.task_id = "task-1"
    ctx.step = "plan"
    ctx.attempt = attempt
    ctx.project_name = project_name
    ctx.input = inp
    ctx.request_id = "req-test"
    if with_requirement:
        ctx.load_artifact = AsyncMock(return_value=b"# Requirement\n\nbuild a todo app")
    else:
        ctx.load_artifact = AsyncMock(side_effect=FileNotFoundError("no requirement"))
    ctx.save_artifact = AsyncMock()
    ctx.heartbeat = AsyncMock()
    return ctx


def _seed_plan_output(workspace: Path, content: str = "# Plan\n\n- m1\n") -> None:
    """模拟 phantom 跑完后留下的 .phantom/plan.locked.md。"""
    (workspace / ".phantom").mkdir(parents=True, exist_ok=True)
    (workspace / ".phantom" / "plan.locked.md").write_text(content)


@pytest.mark.asyncio
async def test_first_run_invokes_phantom_plan_with_requirement_file(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT  # PHANTOM_PROJECTS_BASE/<project>
    ctx = _make_ctx()
    captured_args: list[list[str]] = []
    captured_workspaces: list[Path] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured_args.append(args)
        captured_workspaces.append(workspace)
        _seed_plan_output(workspace)
        return 0

    with patch("ai_plan.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured_workspaces == [workspace]
    assert captured_args == [["--plan", str(workspace / "requirement.md")]]
    assert (workspace / "requirement.md").read_text() == "# Requirement\n\nbuild a todo app"
    # 锁住与上游 ai-requirement worker 一致的产物 key（注意：scheduler 上是 "requirements.md"）
    ctx.load_artifact.assert_awaited_once_with("requirement", "requirements.md")
    ctx.save_artifact.assert_awaited_once()
    args, kwargs = ctx.save_artifact.call_args
    assert args[0] == "plan.md"
    assert "# Plan" in args[1]
    assert kwargs["content_type"] == "text/markdown"
    assert out["rerun"] is False


@pytest.mark.asyncio
async def test_rerun_with_feedback_passes_string_to_phantom(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_output(workspace, "# Old plan\n")
    (workspace / ".phantom" / "state.json").write_text('{"current_phase":"plan"}')

    ctx = _make_ctx(attempt=2, feedback="把 rubric 权重改了")

    captured_args: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured_args.append(args)
        _seed_plan_output(workspace, "# New plan after feedback\n")
        return 0

    with patch("ai_plan.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured_args == [["--plan", "把 rubric 权重改了"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_rerun_without_feedback_uses_synthetic_refresh(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_output(workspace, "# Old plan\n")
    (workspace / ".phantom" / "state.json").write_text('{"current_phase":"plan"}')

    ctx = _make_ctx(attempt=2, feedback=None)

    captured_args: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured_args.append(args)
        _seed_plan_output(workspace, "# Refreshed plan\n")
        return 0

    with patch("ai_plan.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured_args == [["--plan"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_missing_requirement_artifact_raises_fatal(
    tmp_workspace_base: Path,
) -> None:
    ctx = _make_ctx(with_requirement=False)
    with pytest.raises(FatalError, match="requirement"):
        await handle(ctx)


@pytest.mark.asyncio
async def test_phantom_failure_propagates_classified_error(
    tmp_workspace_base: Path,
) -> None:
    from ai_plan.runner import PhantomFailedError

    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        raise PhantomFailedError(1, ["LLM rate limited: try later"])

    with patch("ai_plan.agent.run_phantom", new=fake_run):
        with pytest.raises(RetryableError):
            await handle(ctx)


@pytest.mark.asyncio
async def test_missing_plan_locked_after_phantom_is_fatal(
    tmp_workspace_base: Path,
) -> None:
    """phantom rc=0 但没产出 plan.locked.md → 视为 FatalError（不要静默成功）。"""
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        return 0  # 但不创建 plan.locked.md

    with patch("ai_plan.agent.run_phantom", new=fake_run):
        with pytest.raises(FatalError, match="plan.locked.md"):
            await handle(ctx)


@pytest.mark.asyncio
async def test_empty_project_name_raises_fatal(tmp_workspace_base: Path) -> None:
    """ctx.project_name 是空字符串 → FatalError（resolve_workspace 拒绝）。"""
    ctx = _make_ctx(project_name="")
    with pytest.raises(FatalError, match="project_name"):
        await handle(ctx)
