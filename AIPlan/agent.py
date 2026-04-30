"""ai-plan agent — 包装 phantom 的 plan 模式（aijuicer-sdk 0.6+ 单参 handler）。"""
from __future__ import annotations

import logging
from typing import Any

from aijuicer_sdk import Agent, AgentContext, FatalError

from ai_plan.logging_config import setup_logging
from ai_plan.runner import (
    PhantomFailedError,
    classify_phantom_failure,
    resolve_workspace,
    run_phantom,
    workspace_has_phantom_state,
)

logger = logging.getLogger(__name__)

agent = Agent(name="ai-plan", step="plan", concurrency=1)


def _ctx_tags(ctx: AgentContext) -> str:
    """把 ctx 中的追踪字段拼成日志后缀（user_id 缺失时用 workflow_id 兜底）。"""
    user_id = (ctx.input or {}).get("user_id") if isinstance(ctx.input, dict) else None
    return (
        f"user_id={user_id or '-'} "
        f"workflow_id={getattr(ctx, 'workflow_id', '-')} "
        f"task_id={getattr(ctx, 'task_id', '-')} "
        f"request_id={getattr(ctx, 'request_id', '-')} "
        f"project_name={getattr(ctx, 'project_name', '-')}"
    )


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    tags = _ctx_tags(ctx)
    logger.info("收到 plan 任务，开始处理 %s", tags)

    try:
        workspace = resolve_workspace(ctx.project_name)
    except ValueError as e:
        logger.exception("解析工作区失败 %s", tags)
        raise FatalError(str(e)) from e

    fb_map = ctx.input.get("user_feedback") or {}
    feedback = fb_map.get("plan") if isinstance(fb_map, dict) else None
    # 判断 rerun 用工作区有无 phantom state（.phantom/state.json）；不能用 ctx.attempt：
    # 前几次 attempt 可能因 SDK / 上游问题 fatal，根本没跑到 phantom，工作区还是空的。
    was_initialized = workspace_has_phantom_state(workspace)
    is_rerun = was_initialized

    if was_initialized:
        # 重跑必须用 --plan（增量 amendment 模式）：phantom --resume 会把 design/dev/test
        # 也都跑了，越权；--plan + feedback 则只在 plan 阶段做增量修订并重新落锁。
        if feedback:
            args = ["--plan", feedback]
            logger.info("plan 重跑（amendment），携带用户反馈：%s %s", feedback[:80], tags)
            await ctx.heartbeat(f"plan rerun（用户反馈：{feedback[:40]}）")
        else:
            args = ["--plan"]  # synthetic refresh：phantom 会重走一遍 plan R1→R2→R3
            logger.info("plan 重跑，无反馈，触发纯 refresh %s", tags)
            await ctx.heartbeat("plan rerun（无反馈，纯 refresh）")
    else:
        # 首跑：从上游 requirement step 拉需求文档
        try:
            req_bytes = await ctx.load_artifact("requirement", "requirements.md")
        except FileNotFoundError as e:
            logger.exception("拉取上游 requirement.md 失败 %s", tags)
            raise FatalError(f"上游 requirement.md 不存在：{e}") from e
        req_path = workspace / "requirement.md"
        req_path.write_text(req_bytes.decode("utf-8"))
        args = ["--plan", str(req_path)]
        logger.info("plan 首跑，已写入 requirement.md（%d 字节）%s", len(req_bytes), tags)
        await ctx.heartbeat("plan 首跑（已写入 requirement.md）")

    logger.info("开始调用 phantom CLI args=%s workspace=%s %s", args, workspace, tags)
    try:
        await run_phantom(
            workspace=workspace,
            args=args,
            heartbeat=ctx.heartbeat,
        )
    except PhantomFailedError as e:
        logger.exception("phantom 子进程失败 %s", tags)
        raise classify_phantom_failure(e) from e

    plan_locked = workspace / ".phantom" / "plan.locked.md"
    if not plan_locked.is_file():
        logger.error("phantom 退出码为 0 但未产出 plan.locked.md %s", tags)
        raise FatalError(
            "phantom 跑完但没有产出 .phantom/plan.locked.md，可能是核心章节校验失败。"
        )
    plan_md = plan_locked.read_text(encoding="utf-8")
    await ctx.save_artifact("plan.md", plan_md, content_type="text/markdown")
    logger.info("plan 任务完成，产物 %d 字节，rerun=%s %s", len(plan_md), is_rerun, tags)

    return {"rerun": is_rerun, "bytes": len(plan_md)}


def main() -> None:
    log_file = setup_logging()
    logger.info("ai-plan worker 启动，日志文件=%s", log_file)
    try:
        agent.run()
    except KeyboardInterrupt:
        logger.info("收到 Ctrl+C，ai-plan worker 退出")
    except Exception:
        logger.exception("ai-plan worker 异常退出")
        raise


if __name__ == "__main__":
    main()
