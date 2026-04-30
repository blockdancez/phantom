"""ai_design.py 单测。"""
from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aijuicer_sdk import FatalError

from ai_design.agent import handle


PROJECT = "design-test"


def _make_ctx(
    attempt: int = 1,
    feedback: str | None = None,
    project_name: str = PROJECT,
):
    """0.6+ 单参 handler——所有原 task 字段都挂在 ctx 上。"""
    inp: dict = {"text": "x"}
    if feedback is not None:
        inp["user_feedback"] = {"design": feedback}
    ctx = AsyncMock()
    ctx.workflow_id = "wf-1"
    ctx.task_id = "t-1"
    ctx.step = "design"
    ctx.attempt = attempt
    ctx.project_name = project_name
    ctx.input = inp
    ctx.request_id = "req-1"
    ctx.load_artifact = AsyncMock(return_value=b"# Plan\n\n- f1\n")
    ctx.save_artifact = AsyncMock()
    ctx.heartbeat = AsyncMock()
    return ctx


def _seed_plan_locked(workspace: Path, content: str = "# Plan\n") -> None:
    (workspace / ".phantom").mkdir(parents=True, exist_ok=True)
    (workspace / ".phantom" / "plan.locked.md").write_text(content)
    (workspace / ".phantom" / "state.json").write_text(
        json.dumps({"current_phase": "ui_design", "phases": {"plan": {"status": "completed"}}})
    )


def _seed_design_outputs(workspace: Path, with_html: bool = True) -> None:
    """模拟 phantom --design 跑完后的产物。"""
    d = workspace / ".phantom"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ui-design.md").write_text("# UI Design Overview\n\nproject_id=abc\n")
    if with_html:
        (d / "ui-design").mkdir(exist_ok=True)
        (d / "ui-design" / "home.html").write_text("<html>home</html>")
        (d / "ui-design" / "home.json").write_text("{}")


@pytest.mark.asyncio
async def test_first_run_calls_phantom_design_no_args(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_design_outputs(workspace)
        return 0

    with patch("ai_design.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured == [["--design"]]
    # 应上传 ui-design.md + ui-design.tar.gz
    keys_uploaded = {c.args[0] for c in ctx.save_artifact.call_args_list}
    assert keys_uploaded == {"ui-design.md", "ui-design.tar.gz"}
    assert out["rerun"] is False
    assert out["screens"] == 1


@pytest.mark.asyncio
async def test_rerun_with_feedback_passes_string(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    _seed_design_outputs(workspace)  # 上一次的产物
    ctx = _make_ctx(attempt=2, feedback="改成暖白色调")
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_design_outputs(workspace)
        return 0

    with patch("ai_design.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured == [["--design", "改成暖白色调"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_missing_plan_locked_fetches_from_artifact(
    tmp_workspace_base: Path,
) -> None:
    """同一 wf 但 design agent 跑在不同机器（plan.locked.md 不在本地） → 从 artifact 拉。"""
    # 不 seed plan_locked；workspace 由 resolve_workspace 自动创建
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        # 验证 phantom 跑之前 plan.locked.md 已经被写好了
        assert (workspace / ".phantom" / "plan.locked.md").exists()
        _seed_design_outputs(workspace)
        return 0

    with patch("ai_design.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    ctx.load_artifact.assert_awaited_once_with("plan", "plan.md")
    assert out["rerun"] is False


@pytest.mark.asyncio
async def test_no_html_means_pure_backend_project(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        # 只写 ui-design.md，不写 ui-design/ 目录（纯后端 fallback）
        (workspace / ".phantom").mkdir(exist_ok=True)
        (workspace / ".phantom" / "ui-design.md").write_text("纯后端项目，无需 UI 设计\n")
        return 0

    with patch("ai_design.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    keys = {c.args[0] for c in ctx.save_artifact.call_args_list}
    assert keys == {"ui-design.md"}  # 不上传 tar.gz
    assert out["screens"] == 0


@pytest.mark.asyncio
async def test_missing_ui_design_md_after_phantom_is_fatal(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        return 0  # 不写任何产物

    with patch("ai_design.agent.run_phantom", new=fake_run):
        with pytest.raises(FatalError, match="ui-design.md"):
            await handle(ctx)


@pytest.mark.asyncio
async def test_tarball_contains_html_files(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_plan_locked(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_design_outputs(workspace, with_html=True)
        return 0

    with patch("ai_design.agent.run_phantom", new=fake_run):
        await handle(ctx)

    # 找到 tar.gz 的 save_artifact 调用，解开看里面文件
    tar_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "ui-design.tar.gz"]
    assert len(tar_calls) == 1
    raw = tar_calls[0].args[1]
    assert isinstance(raw, (bytes, bytearray))
    with tarfile.open(fileobj=BytesIO(raw), mode="r:gz") as tf:
        names = tf.getnames()
    assert "ui-design/home.html" in names
    assert "ui-design/home.json" in names
