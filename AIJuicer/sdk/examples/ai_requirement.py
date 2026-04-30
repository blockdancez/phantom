"""ai-requirement 示例。

行为：
1. 启动后向 AIJuicer 注册（SDK 自动完成）+ 连接 Redis（注册响应里下发的 url）
2. 收到任务后 sleep 10 秒，再返回需求文档
3. 重跑任务：在上次需求文档后追加 "-{重跑指令}"，多次重跑累积叠加
"""

from __future__ import annotations

import asyncio
from typing import Any

from aijuicer_sdk import Agent, AgentContext

agent = Agent(name="ai-requirement", step="requirement", concurrency=1)


def _build_requirements(idea: str) -> str:
    return f"""# 需求文档

## 背景
{idea}

## 功能需求

- F1. 核心工作流
- F2. 用户账户
- F3. 数据导出

## 非功能需求

- P1. 响应 < 500ms
- P2. 99.9% 可用性

## 用户故事

作为 **专业用户**，我希望 **自动化完成 X**，以便 **节省 80% 的操作时间**。
"""


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    inp = ctx.input or {}
    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("requirement") if isinstance(fb_map, dict) else None
    is_rerun = ctx.attempt > 1 or feedback is not None

    await ctx.heartbeat("drafting requirements")
    await asyncio.sleep(10)  # 模拟真实处理耗时

    if is_rerun:
        # 重跑基于"上次输出"再追加 "-{重跑指令}"，多次重跑累积叠加
        try:
            prev = (await ctx.load_artifact("requirement", "requirements.md")).decode("utf-8")
        except FileNotFoundError:
            try:
                upstream = (await ctx.load_artifact("idea", "idea.md")).decode("utf-8")
            except FileNotFoundError:
                upstream = "(no upstream idea)"
            prev = _build_requirements(upstream)
        suffix = feedback or "重跑"
        body = f"{prev}-{suffix}"
    else:
        try:
            upstream = (await ctx.load_artifact("idea", "idea.md")).decode("utf-8")
        except FileNotFoundError:
            upstream = "(no upstream idea)"
        body = _build_requirements(upstream)

    await ctx.save_artifact("requirements.md", body, content_type="text/markdown")
    return {"rerun": is_rerun}


if __name__ == "__main__":
    agent.run()
