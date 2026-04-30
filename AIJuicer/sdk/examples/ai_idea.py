"""ai-idea 完整示例。

行为：
1. 启动后向 AIJuicer 注册（SDK 自动完成）+ 连接 Redis（注册响应里下发的 url）
2. 后台开一个生成器循环，每 10 分钟随机产生一个 idea，
   通过 SDK 主动 POST 到 /api/workflows 创建一条工作流
   （只是这个 example 用来模拟"持续产生 idea 的真实场景"，
    并不是 SDK 的内置能力——SDK 只暴露 SchedulerClient.create_workflow 这块原语）
3. 作为 idea 步的 handler 处理任务；若是重跑（attempt > 1 或带 user_feedback），
   在 idea 文本末尾追加 "-{重跑指令}"，再保存为产物（多次重跑会累积叠加）

Run 方式：python -m sdk.examples.ai_idea
"""

from __future__ import annotations

import asyncio
import os
import random
import uuid
from typing import Any

import structlog
from aijuicer_sdk import Agent, AgentContext, slugify_idea
from aijuicer_sdk.transport import SchedulerClient

# ── 配置 ──────────────────────────────────────────────────────────────────
GENERATE_INTERVAL_SEC = float(os.environ.get("AI_IDEA_INTERVAL_SEC", "600"))
SEED_IDEAS = [
    "面向大学生的 AI 课程笔记助手",
    "AI 简历自动优化工具",
    "AI 站会纪要生成器",
    "AI 邮件分类与自动回复助手",
    "AI 旅行行程规划助手",
    "AI 小红书选题与文案生成器",
    "AI 学习计划生成与跟踪 App",
    "AI 健身教练 + 饮食建议",
    "AI 法律合同条款审阅工具",
    "AI 客服知识库自动维护",
]
# ── Agent：handler（消费侧）────────────────────────────────────────────────
agent = Agent(name="ai-idea", step="idea", concurrency=1)


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    inp = ctx.input or {}
    text = inp.get("text") or inp.get("topic") or ""
    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("idea") if isinstance(fb_map, dict) else None
    is_rerun = ctx.attempt > 1 or feedback is not None

    await ctx.heartbeat("recording idea")
    await asyncio.sleep(10)  # 模拟真实处理耗时

    if is_rerun:
        # 重跑基于"上次输出"再追加 "-{重跑指令}"，多次重跑累积叠加
        try:
            prev = (await ctx.load_artifact(step="idea", key="idea.md")).decode("utf-8")
        except FileNotFoundError:
            prev = text
        suffix = feedback or "重跑"  # 重跑但没填指令时退化为字面 "重跑"
        body = f"{prev}-{suffix}"
    else:
        body = text

    await ctx.save_artifact("idea.md", body, content_type="text/markdown")
    return {"text": body, "rerun": is_rerun}


# ── Generator：每 5 分钟主动生成 idea（仅本 example 行为）────────────────────
async def periodic_idea_generator(server: str, log: Any) -> None:
    """独立于 agent 主循环的 producer：每 GENERATE_INTERVAL_SEC 生成一条新工作流。"""
    client = SchedulerClient(server)
    try:
        while True:
            try:
                topic = random.choice(SEED_IDEAS)
                short = uuid.uuid4().hex[:6]
                # approval_policy 留空 → 后续每个 step 都默认走 AWAITING_APPROVAL
                # （需要人工确认）。要改成全自动可显式传 {step: "auto", ...}。
                wf = await client.create_workflow(
                    name=f"auto · {topic} · {short}",
                    project_name=slugify_idea(topic),
                    input={"text": topic},
                )
                await log.ainfo("自动创建工作流", workflow_id=wf["id"], topic=topic)
            except Exception as e:  # noqa: BLE001 — 单次失败不应让循环退出
                await log.awarning("自动创建工作流失败", error=str(e))
            await asyncio.sleep(GENERATE_INTERVAL_SEC)
    finally:
        await client.close()


async def main() -> None:
    server = os.environ.get("AIJUICER_SERVER", "http://localhost:8000")
    # 自动生成器默认关闭——避免每次起 example 就往 DB 灌 idea。
    # 想模拟"持续产生 idea 的场景"时显式开启：AI_IDEA_AUTO_GENERATE=1
    auto = os.environ.get("AI_IDEA_AUTO_GENERATE", "0").lower() in ("1", "true", "yes")
    producer: asyncio.Task[None] | None = None
    if auto:
        producer_log = structlog.get_logger("ai_idea.producer")
        producer = asyncio.create_task(periodic_idea_generator(server, producer_log))
    try:
        await agent.arun()
    finally:
        if producer is not None:
            producer.cancel()
            try:
                await producer
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass


if __name__ == "__main__":
    asyncio.run(main())
