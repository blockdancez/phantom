"""最小 demo：回显 input.topic 并写一个 idea.md 产物。

启动：
    export AIJUICER_SERVER=http://localhost:8000
    export AIJUICER_REDIS_URL=redis://localhost:6379/0
    python -m sdk.examples.echo_agent
"""

from __future__ import annotations

from aijuicer_sdk import Agent

agent = Agent(name="echo-finder", step="finder", concurrency=1)


@agent.handler
async def handle(ctx, task):
    topic = (task.get("input") or {}).get("topic", "<no topic>")
    await ctx.heartbeat("echo.start")
    text = f"# Echo finder\n\ntopic: {topic}\n"
    await ctx.save_artifact("idea.md", text)
    return {"echo": topic, "bytes": len(text)}


if __name__ == "__main__":
    agent.run()
