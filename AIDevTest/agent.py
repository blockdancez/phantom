"""ai-devtest agent — 包装 phantom 的 dev-test 模式。"""
from __future__ import annotations

import io
import json
import logging
import re
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aijuicer_sdk import Agent, AgentContext, FatalError

from ai_devtest.logging_config import setup_logging
from ai_devtest.runner import (
    PhantomFailedError,
    classify_phantom_failure,
    resolve_workspace,
    run_phantom,
)

logger = logging.getLogger(__name__)

agent = Agent(name="ai-devtest", step="devtest", concurrency=1)


def _ctx_tags(ctx: AgentContext) -> str:
    user_id = (ctx.input or {}).get("user_id") if isinstance(ctx.input, dict) else None
    return (
        f"user_id={user_id or '-'} "
        f"workflow_id={getattr(ctx, 'workflow_id', '-')} "
        f"task_id={getattr(ctx, 'task_id', '-')} "
        f"request_id={getattr(ctx, 'request_id', '-')} "
        f"project_name={getattr(ctx, 'project_name', '-')}"
    )


def _bootstrap_state_for_devtest(workspace: Path, plan_md: str) -> None:
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plan.locked.md").write_text(plan_md)
    (pdir / "state.json").write_text(
        json.dumps(
            {
                "requirements_file": str(workspace / "requirement.md"),
                "project_dir": str(workspace),
                "current_phase": "dev",
                "current_group_index": 0,
                "phases": {
                    "plan": {"status": "completed", "iteration": 1},
                    "ui_design": {"status": "completed", "iteration": 1},
                    "dev": {"status": "pending", "iteration": 0},
                    "code_review": {"status": "pending", "iteration": 0},
                    "deploy": {"status": "pending", "iteration": 0},
                    "test": {"status": "pending", "iteration": 0, "forced_features": []},
                },
                "started_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
            }
        )
    )
    (pdir / "changelog.md").touch()


def _restore_design_if_available(workspace: Path, ui_design_md: str | None) -> None:
    if ui_design_md is None:
        return
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "ui-design.md").write_text(ui_design_md)


def _make_code_tarball(workspace: Path) -> bytes:
    """打包 backend/ frontend/ scripts/ 三个目录（存在的话），跳过 .phantom/。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        for sub in ("backend", "frontend", "scripts"):
            sub_dir = workspace / sub
            if sub_dir.is_dir():
                tf.add(sub_dir, arcname=sub)
    return buf.getvalue()


def _latest_test_report(workspace: Path) -> Path | None:
    """从 .phantom/test-report-iter<N>.md 里挑出 N 最大的那份。"""
    pdir = workspace / ".phantom"
    if not pdir.is_dir():
        return None
    candidates: list[tuple[int, Path]] = []
    pat = re.compile(r"^test-report-iter(\d+)\.md$")
    for p in pdir.iterdir():
        m = pat.match(p.name)
        if m:
            candidates.append((int(m.group(1)), p))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _runtime_summary(workspace: Path) -> dict[str, Any]:
    pdir = workspace / ".phantom"
    out: dict[str, Any] = {}
    bp = pdir / "port.backend"
    if bp.is_file():
        out["backend_port"] = int(bp.read_text().strip())
    fp = pdir / "port.frontend"
    if fp.is_file():
        out["frontend_port"] = int(fp.read_text().strip())
    pid = pdir / "runtime" / "backend.pid"
    if pid.is_file():
        out["backend_pid"] = int(pid.read_text().strip())
    return out


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    tags = _ctx_tags(ctx)
    logger.info("收到 devtest 任务，开始处理 %s", tags)

    try:
        workspace = resolve_workspace(ctx.project_name)
    except ValueError as e:
        logger.exception("解析工作区失败 %s", tags)
        raise FatalError(str(e)) from e

    fb_map = ctx.input.get("user_feedback") or {}
    feedback = fb_map.get("devtest") if isinstance(fb_map, dict) else None
    changelog = workspace / ".phantom" / "changelog.md"
    is_rerun = changelog.is_file() and "## Iteration " in changelog.read_text(errors="replace")

    plan_locked = workspace / ".phantom" / "plan.locked.md"
    if not plan_locked.is_file():
        try:
            plan_md = (await ctx.load_artifact("plan", "plan.md")).decode("utf-8")
        except FileNotFoundError as e:
            logger.exception("拉取上游 plan.md 失败 %s", tags)
            raise FatalError(f"上游 plan.md 不存在：{e}") from e
        _bootstrap_state_for_devtest(workspace, plan_md)
        # design 是 best-effort：拉得到就用，拉不到不阻塞
        try:
            ui_md = (await ctx.load_artifact("design", "ui-design.md")).decode("utf-8")
            _restore_design_if_available(workspace, ui_md)
            logger.info("已从 artifact 拉取 ui-design.md（%d 字节）%s", len(ui_md), tags)
        except FileNotFoundError:
            logger.info("上游 ui-design.md 不存在，跳过（phantom 在 dev 阶段会按通用规范降级）%s", tags)
        logger.info("已 bootstrap 工作区（plan %d 字节）%s", len(plan_md), tags)
        await ctx.heartbeat("从 artifact 拉了 plan.locked.md（design 可选），已 bootstrap 工作区")

    # 首跑/重跑都用 --dev-test：phantom --dev-test 模式只跑 dev → code-review → deploy → test。
    # 不能用 --resume：phantom 的 --resume 不限制阶段，可能越界跑。
    args = ["--dev-test", feedback] if feedback else ["--dev-test"]
    logger.info("开始调用 phantom CLI args=%s workspace=%s rerun=%s %s", args, workspace, is_rerun, tags)
    await ctx.heartbeat(f"dev-test {'rerun' if is_rerun else '首跑'}")

    try:
        await run_phantom(workspace=workspace, args=args, heartbeat=ctx.heartbeat)
    except PhantomFailedError as e:
        logger.exception("phantom 子进程失败 %s", tags)
        raise classify_phantom_failure(e) from e

    test_report = _latest_test_report(workspace)
    if test_report is None:
        logger.error("phantom 退出码为 0 但未产出任何 test-report-iter*.md %s", tags)
        raise FatalError(
            "phantom dev-test 跑完但没产出任何 .phantom/test-report-iter*.md，无法验证开发结果。"
        )
    await ctx.save_artifact(
        "test-report.md",
        test_report.read_text(encoding="utf-8"),
        content_type="text/markdown",
    )

    code_tar = _make_code_tarball(workspace)
    await ctx.save_artifact("code.tar.gz", code_tar, content_type="application/gzip")

    runtime = _runtime_summary(workspace)
    await ctx.save_artifact(
        "runtime.json",
        json.dumps(runtime, ensure_ascii=False),
        content_type="application/json",
    )

    iter_num = int(re.search(r"iter(\d+)", test_report.name).group(1))
    logger.info(
        "devtest 任务完成，code=%d 字节 test_report_iter=%d runtime=%s rerun=%s %s",
        len(code_tar), iter_num, runtime, is_rerun, tags,
    )
    return {
        "rerun": is_rerun,
        "code_bytes": len(code_tar),
        "test_report_iter": iter_num,
    }


def main() -> None:
    log_file = setup_logging()
    logger.info("ai-devtest worker 启动，日志文件=%s", log_file)
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，ai-devtest worker 退出")
    except Exception:
        logger.exception("ai-devtest worker 异常退出")
        raise


if __name__ == "__main__":
    main()
