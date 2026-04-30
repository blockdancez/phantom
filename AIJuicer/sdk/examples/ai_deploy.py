"""ai-deploy 示例。

行为：
1. 启动后向 AIJuicer 注册（SDK 自动完成）+ 连接 Redis（注册响应里下发的 url）
2. 收到任务后 sleep 10 秒，再返回项目访问地址
3. 重跑任务：在上次站点 URL 末尾追加 "1"，区分重跑后的版本（多次重跑会累积成 ...11、...111）
"""

from __future__ import annotations

import asyncio
from typing import Any

from aijuicer_sdk import Agent, AgentContext

agent = Agent(name="ai-deploy", step="deploy", concurrency=1)

# 占位：真实场景应调用 Vercel/Netlify/Kubernetes/etc. 部署后拿到生产 URL
SITE_URL = "https://ai-app.example.com"


@agent.handler
async def handle(ctx: AgentContext) -> dict[str, Any]:
    inp = ctx.input or {}
    fb_map = inp.get("user_feedback") or {}
    feedback = fb_map.get("deploy") if isinstance(fb_map, dict) else None
    is_rerun = ctx.attempt > 1 or feedback is not None

    await ctx.heartbeat("deploying to production")
    await asyncio.sleep(10)  # 模拟真实处理耗时

    if is_rerun:
        try:
            prev = (await ctx.load_artifact("deploy", "site.url")).decode("utf-8").rstrip("\n")
        except FileNotFoundError:
            prev = SITE_URL
        url = f"{prev}1"
    else:
        url = SITE_URL

    body = url + "\n"
    await ctx.save_artifact("site.url", body, content_type="text/uri-list")
    return {"site_url": url, "rerun": is_rerun}


if __name__ == "__main__":
    agent.run()
