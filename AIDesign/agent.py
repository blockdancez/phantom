"""ai-design agent — 包装 phantom 的 design 模式。"""
from __future__ import annotations

import io
import json
import logging
import tarfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from aijuicer_sdk import Agent, AgentContext, FatalError

from ai_design.logging_config import setup_logging
from ai_design.runner import (
    PhantomFailedError,
    classify_phantom_failure,
    resolve_workspace,
    run_phantom,
    workspace_has_phantom_state,
)

logger = logging.getLogger(__name__)

agent = Agent(name="ai-design", step="design", concurrency=1)


def _ctx_tags(ctx: AgentContext) -> str:
    user_id = (ctx.input or {}).get("user_id") if isinstance(ctx.input, dict) else None
    return (
        f"user_id={user_id or '-'} "
        f"workflow_id={getattr(ctx, 'workflow_id', '-')} "
        f"task_id={getattr(ctx, 'task_id', '-')} "
        f"request_id={getattr(ctx, 'request_id', '-')} "
        f"project_name={getattr(ctx, 'project_name', '-')}"
    )


def _bootstrap_state_for_design(workspace: Path, plan_md: str) -> None:
    """plan.locked.md 不在本地（多机部署） → 从 artifact 落到本地 + 写最小 state.json。

    phantom --design 模式只读 .phantom/plan.locked.md + .phantom/state.json；
    其它字段（changelog 等）不读，所以一份最小骨架就够。
    """
    pdir = workspace / ".phantom"
    pdir.mkdir(parents=True, exist_ok=True)
    (pdir / "plan.locked.md").write_text(plan_md)
    (pdir / "state.json").write_text(
        json.dumps(
            {
                "requirements_file": str(workspace / "requirement.md"),
                "project_dir": str(workspace),
                "current_phase": "ui_design",
                "current_group_index": 0,
                "phases": {
                    "plan": {"status": "completed", "iteration": 1},
                    "ui_design": {"status": "pending", "iteration": 0},
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


def _make_ui_design_tarball(ui_design_dir: Path) -> bytes:
    """把 .phantom/ui-design/ 目录打成 tar.gz 字节流。"""
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as tf:
        tf.add(ui_design_dir, arcname="ui-design")
    return buf.getvalue()


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    tags = _ctx_tags(ctx)
    logger.info("收到 design 任务，开始处理 %s", tags)

    try:
        workspace = resolve_workspace(ctx.project_name)
    except ValueError as e:
        logger.exception("解析工作区失败 %s", tags)
        raise FatalError(str(e)) from e

    fb_map = ctx.input.get("user_feedback") or {}
    feedback = fb_map.get("design") if isinstance(fb_map, dict) else None
    is_rerun = (workspace / ".phantom" / "ui-design.md").is_file()

    plan_locked = workspace / ".phantom" / "plan.locked.md"
    if not plan_locked.is_file():
        try:
            plan_md = (await ctx.load_artifact("plan", "plan.md")).decode("utf-8")
        except FileNotFoundError as e:
            logger.exception("拉取上游 plan.md 失败 %s", tags)
            raise FatalError(f"上游 plan.md 不存在：{e}") from e
        _bootstrap_state_for_design(workspace, plan_md)
        logger.info("已从 artifact 拉取 plan.locked.md 并 bootstrap 工作区（%d 字节）%s", len(plan_md), tags)
        await ctx.heartbeat("从 artifact 拉了 plan.locked.md，已 bootstrap 工作区")
    elif not workspace_has_phantom_state(workspace):
        _bootstrap_state_for_design(workspace, plan_locked.read_text())
        logger.info("plan.locked.md 已存在但 state.json 缺失，已补 bootstrap %s", tags)

    # 首跑/重跑都用 --design：phantom --design 模式只跑 design phase（design → review → design）。
    # 不能用 --resume：那会从 state.json 当前阶段一路跑到 dev/test/deploy，越权。
    args = ["--design", feedback] if feedback else ["--design"]
    logger.info("开始调用 phantom CLI args=%s workspace=%s rerun=%s %s", args, workspace, is_rerun, tags)
    await ctx.heartbeat(f"design {'rerun' if is_rerun else '首跑'}")

    try:
        await run_phantom(workspace=workspace, args=args, heartbeat=ctx.heartbeat)
    except PhantomFailedError as e:
        logger.exception("phantom 子进程失败 %s", tags)
        raise classify_phantom_failure(e) from e

    ui_design_md = workspace / ".phantom" / "ui-design.md"
    if not ui_design_md.is_file():
        logger.error("phantom 退出码为 0 但未产出 ui-design.md %s", tags)
        raise FatalError(
            "phantom 跑完但没产出 .phantom/ui-design.md（前端项目应该有，纯后端 fallback 也应留一份）"
        )
    md_text = ui_design_md.read_text(encoding="utf-8")
    await ctx.save_artifact("ui-design.md", md_text, content_type="text/markdown")

    ui_design_dir = workspace / ".phantom" / "ui-design"
    screen_count = 0
    if ui_design_dir.is_dir():
        screen_count = sum(1 for p in ui_design_dir.glob("*.html"))
    if screen_count > 0:
        tar_bytes = _make_ui_design_tarball(ui_design_dir)
        await ctx.save_artifact(
            "ui-design.tar.gz",
            tar_bytes,
            content_type="application/gzip",
        )

    logger.info("design 任务完成，screens=%d rerun=%s %s", screen_count, is_rerun, tags)
    return {"rerun": is_rerun, "screens": screen_count}


def main() -> None:
    log_file = setup_logging()
    logger.info("ai-design worker 启动，日志文件=%s", log_file)
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，ai-design worker 退出")
    except Exception:
        logger.exception("ai-design worker 异常退出")
        raise


if __name__ == "__main__":
    main()
