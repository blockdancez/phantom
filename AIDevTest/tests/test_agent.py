"""ai_devtest.py 单测。"""
from __future__ import annotations

import json
import tarfile
from io import BytesIO
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest
from aijuicer_sdk import FatalError

from ai_devtest.agent import handle


PROJECT = "devtest-test"


def _make_ctx(
    attempt: int = 1,
    feedback: str | None = None,
    project_name: str = PROJECT,
):
    """0.6+ 单参 handler——所有原 task 字段都挂在 ctx 上。"""
    inp: dict = {"text": "x"}
    if feedback is not None:
        inp["user_feedback"] = {"devtest": feedback}
    ctx = AsyncMock()
    ctx.workflow_id = "wf-1"
    ctx.task_id = "t-1"
    ctx.step = "devtest"
    ctx.attempt = attempt
    ctx.project_name = project_name
    ctx.input = inp
    ctx.request_id = "req-1"
    ctx.load_artifact = AsyncMock(return_value=b"# Plan\n\n- f1\n")
    ctx.save_artifact = AsyncMock()
    ctx.heartbeat = AsyncMock()
    return ctx


def _seed_phantom_state(workspace: Path) -> None:
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plan.locked.md").write_text("# Plan\n")
    (pdir / "state.json").write_text(json.dumps({"current_phase": "dev", "phases": {}}))
    (pdir / "changelog.md").touch()


def _seed_devtest_outputs(workspace: Path, iter_n: int = 1, with_frontend: bool = True) -> None:
    """模拟 phantom --dev-test 跑完后的产物。"""
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / f"test-report-iter{iter_n}.md").write_text(f"# Test Report iter {iter_n}\n\n总分: 92/100\n")
    # 模拟 phantom 在 changelog.md 追加了一节 Iteration（rerun 检测靠它）
    changelog = pdir / "changelog.md"
    existing = changelog.read_text() if changelog.is_file() else ""
    changelog.write_text(existing + f"\n## Iteration {iter_n}\n")
    (pdir / "port.backend").write_text("12345")
    (pdir / "port.frontend").write_text("12346") if with_frontend else None
    (pdir / "runtime").mkdir(exist_ok=True)
    (pdir / "runtime" / "backend.pid").write_text("9999")
    # 业务代码
    (workspace / "backend").mkdir(exist_ok=True)
    (workspace / "backend" / "app.py").write_text("from fastapi import FastAPI\napp = FastAPI()\n")
    if with_frontend:
        (workspace / "frontend").mkdir(exist_ok=True)
        (workspace / "frontend" / "index.html").write_text("<html></html>")
    (workspace / "scripts").mkdir(exist_ok=True)
    (workspace / "scripts" / "start-backend.sh").write_text("#!/bin/bash\nexec uvicorn ...")


@pytest.mark.asyncio
async def test_first_run_calls_phantom_dev_test_no_args(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_devtest_outputs(workspace)
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured == [["--dev-test"]]
    keys = {c.args[0] for c in ctx.save_artifact.call_args_list}
    assert "code.tar.gz" in keys
    assert "test-report.md" in keys
    assert "runtime.json" in keys
    assert out["rerun"] is False


@pytest.mark.asyncio
async def test_rerun_with_feedback_passes_string(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    _seed_devtest_outputs(workspace, iter_n=1)
    ctx = _make_ctx(attempt=2, feedback="搜索按钮点了没反应")
    captured: list[list[str]] = []

    async def fake_run(*, workspace, args, heartbeat, **kw):
        captured.append(args)
        _seed_devtest_outputs(workspace, iter_n=2)
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        out = await handle(ctx)

    assert captured == [["--dev-test", "搜索按钮点了没反应"]]
    assert out["rerun"] is True


@pytest.mark.asyncio
async def test_test_report_picks_latest_iter(tmp_workspace_base: Path) -> None:
    """有多份 test-report-iterN.md → 上传最大 N 的那份。"""
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_devtest_outputs(workspace, iter_n=1)
        _seed_devtest_outputs(workspace, iter_n=3)  # 也写一份 iter-3
        _seed_devtest_outputs(workspace, iter_n=2)
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        await handle(ctx)

    test_report_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "test-report.md"]
    assert len(test_report_calls) == 1
    body = test_report_calls[0].args[1]
    assert "iter 3" in body  # 最新一份


@pytest.mark.asyncio
async def test_runtime_json_has_ports_and_pid(tmp_workspace_base: Path) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_devtest_outputs(workspace, with_frontend=True)
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        await handle(ctx)

    runtime_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "runtime.json"]
    assert len(runtime_calls) == 1
    payload = json.loads(runtime_calls[0].args[1])
    assert payload == {"backend_port": 12345, "frontend_port": 12346, "backend_pid": 9999}


@pytest.mark.asyncio
async def test_code_tarball_contains_backend_frontend_scripts(
    tmp_workspace_base: Path,
) -> None:
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        _seed_devtest_outputs(workspace, with_frontend=True)
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        await handle(ctx)

    tar_calls = [c for c in ctx.save_artifact.call_args_list if c.args[0] == "code.tar.gz"]
    assert len(tar_calls) == 1
    raw = tar_calls[0].args[1]
    with tarfile.open(fileobj=BytesIO(raw), mode="r:gz") as tf:
        names = tf.getnames()
    assert "backend/app.py" in names
    assert "frontend/index.html" in names
    assert "scripts/start-backend.sh" in names
    # .phantom/ 不应在打包里（会引入 runtime/ logs/ 等噪声）
    assert not any(n.startswith(".phantom") for n in names)


@pytest.mark.asyncio
async def test_missing_plan_locked_fetches_both_plan_and_design(
    tmp_workspace_base: Path,
) -> None:
    """devtest 在新机器跑：plan + design 都从 artifact 拉。"""
    ctx = _make_ctx()

    # 区分 plan 和 design 的产物 mock
    async def load_artifact_dispatch(step: str, key: str) -> bytes:
        if step == "plan":
            return b"# Plan\n"
        if step == "design":
            return b"# UI Design Overview\n"
        raise FileNotFoundError(f"no {step}/{key}")

    ctx.load_artifact = AsyncMock(side_effect=load_artifact_dispatch)

    async def fake_run(*, workspace, args, heartbeat, **kw):
        assert (workspace / ".phantom" / "plan.locked.md").exists()
        # design 是 best-effort（design artifact 拉到了就放进去；拉不到不阻塞）
        _seed_devtest_outputs(workspace)
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        await handle(ctx)

    # 至少调用了 plan.md 拉取
    plan_calls = [c for c in ctx.load_artifact.call_args_list if c.args == ("plan", "plan.md")]
    assert len(plan_calls) == 1


@pytest.mark.asyncio
async def test_missing_test_report_is_fatal(tmp_workspace_base: Path) -> None:
    """phantom rc=0 但没产出任何 test-report-iter*.md → fatal。"""
    workspace = tmp_workspace_base / PROJECT
    workspace.mkdir(parents=True)
    _seed_phantom_state(workspace)
    ctx = _make_ctx()

    async def fake_run(*, workspace, args, heartbeat, **kw):
        # 不写 test-report
        (workspace / ".phantom").mkdir(exist_ok=True)
        (workspace / "backend").mkdir(exist_ok=True)
        (workspace / "backend" / "x.py").write_text("")
        return 0

    with patch("ai_devtest.agent.run_phantom", new=fake_run):
        with pytest.raises(FatalError, match="test-report"):
            await handle(ctx)
