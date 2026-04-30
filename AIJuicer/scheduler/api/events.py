"""/api/workflows/{id}/events —— SSE 实时推送（spec § 7.4）。"""

from __future__ import annotations

import asyncio
import json
import uuid
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from sse_starlette.sse import EventSourceResponse

from scheduler.engine.event_bus import get_event_bus
from scheduler.observability.logging import get_logger

logger = get_logger(__name__)
router = APIRouter(prefix="/api/workflows", tags=["events"])


@router.get("/{wf_id}/events")
async def workflow_events(wf_id: uuid.UUID, request: Request) -> EventSourceResponse:
    bus = get_event_bus()
    queue = bus.subscribe(wf_id)
    logger.info("SSE 客户端订阅工作流事件", workflow_id=str(wf_id))

    async def stream() -> AsyncIterator[dict]:
        try:
            # 初始一个 ready 事件便于前端确认连接建立
            yield {"event": "ready", "data": json.dumps({"workflow_id": str(wf_id)})}
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(queue.get(), timeout=15.0)
                except TimeoutError:
                    # keepalive 注释（sse_starlette 会转成 ": ping\n\n"）
                    yield {"comment": "ping"}
                    continue
                yield {
                    "event": ev["event_type"],
                    "data": json.dumps(
                        {
                            "event_type": ev["event_type"],
                            "payload": ev.get("payload", {}),
                            "request_id": ev.get("request_id"),
                        },
                        default=str,
                    ),
                }
        finally:
            bus.unsubscribe(wf_id, queue)
            logger.info("SSE 客户端取消订阅", workflow_id=str(wf_id))

    return EventSourceResponse(stream())
