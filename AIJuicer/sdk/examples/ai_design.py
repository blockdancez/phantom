"""ai-design 示例。

行为：
1. 启动后向 AIJuicer 注册（SDK 自动完成）+ 连接 Redis（注册响应里下发的 url）
2. 收到任务后 sleep 10 秒，再返回设计文档 URL
3. 重跑任务：在上次 URL 末尾追加 "1"，区分重跑后的版本（多次重跑会累积成 ...11、...111）
"""

from __future__ import annotations

import asyncio
from typing import Any

from aijuicer_sdk import Agent, AgentContext

agent = Agent(name="ai-design", step="design", concurrency=1)

# 占位：真实场景应调用设计平台 API 创建文件并拿到分享链接
DESIGN_URL = "https://www.figma.com/file/example-design/AI-App?node-id=0-1"


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    inp = ctx.input or {}
    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("design") if isinstance(fb_map, dict) else None
    is_rerun = ctx.attempt > 1 or feedback is not None

    await ctx.heartbeat("creating design draft")
    await asyncio.sleep(10)  # 模拟真实处理耗时

    if is_rerun:
        try:
            prev = (await ctx.load_artifact("design", "design.url")).decode("utf-8").rstrip("\n")
        except FileNotFoundError:
            prev = DESIGN_URL
        url = f"{prev}1"
    else:
        url = DESIGN_URL

    body = url + "\n"
    await ctx.save_artifact("design.url", body, content_type="text/uri-list")
    return {"design_url": url, "rerun": is_rerun}


if __name__ == "__main__":
    agent.run()
