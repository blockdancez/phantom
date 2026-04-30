"""AIClusterSchedule Agent SDK（M2 最小可用）。

典型用法：

    from aijuicer_sdk import Agent, RetryableError, FatalError

    agent = Agent(name="ai-finder", step="finder",
                  server="http://localhost:8000",
                  redis_url="redis://localhost:6379/0")

    @agent.handler
    async def handle(ctx, task):
        await ctx.heartbeat("thinking")
        return {"idea": "..."}

    if __name__ == "__main__":
        agent.run()
"""

from __future__ import annotations

from aijuicer_sdk.agent import Agent
from aijuicer_sdk.context import AgentContext, ArtifactRef
from aijuicer_sdk.errors import FatalError, RetryableError
from aijuicer_sdk.slug import slugify_idea
from aijuicer_sdk.types import HandlerOutput, TaskPayload

__all__ = [
    "Agent",
    "AgentContext",
    "ArtifactRef",
    "FatalError",
    "HandlerOutput",
    "RetryableError",
    "TaskPayload",
    "slugify_idea",
]
