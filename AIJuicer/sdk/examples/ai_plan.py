"""ai-plan 示例。

行为：
1. 启动后向 AIJuicer 注册（SDK 自动完成）+ 连接 Redis（注册响应里下发的 url）
2. 收到任务后 sleep 10 秒，再返回计划文档
3. 重跑任务：在上次计划文档后追加 "-{重跑指令}"，多次重跑累积叠加
"""

from __future__ import annotations

import asyncio
from typing import Any

from aijuicer_sdk import Agent, AgentContext

agent = Agent(name="ai-plan", step="plan", concurrency=1)


def _build_plan() -> str:
    return (
        "# 实施计划\n\n"
        "- **M1** — 后端骨架 · 预计 2 周\n"
        "- **M2** — Agent SDK · 预计 1 周\n"
        "- **M3** — 可恢复性 · 预计 1 周\n"
        "- **M4** — Web UI · 预计 2 周\n"
    )


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    inp = ctx.input or {}
    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("plan") if isinstance(fb_map, dict) else None
    is_rerun = ctx.attempt > 1 or feedback is not None

    await ctx.heartbeat("planning milestones")
    await asyncio.sleep(10)  # 模拟真实处理耗时

    if is_rerun:
        try:
            prev = (await ctx.load_artifact("plan", "plan.md")).decode("utf-8")
        except FileNotFoundError:
            prev = _build_plan()
        suffix = feedback or "重跑"
        body = f"{prev}-{suffix}"
    else:
        body = _build_plan()

    await ctx.save_artifact("plan.md", body, content_type="text/markdown")
    return {"rerun": is_rerun}


if __name__ == "__main__":
    agent.run()
