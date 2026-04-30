"""进程内事件总线（M5 SSE 依赖）。

每个 workflow 维护一组订阅者 queue；service 层在 DB commit 后 publish。单进程
FastAPI 足够。未来多副本部署换成 Postgres LISTEN/NOTIFY 或 Redis pub/sub。
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from typing import Any

from scheduler.observability.logging import get_logger

logger = get_logger(__name__)

_MAX_QUEUE = 256  # 慢消费者被丢 event 而不是阻塞 publish


class EventBus:
    def __init__(self) -> None:
        self._subs: dict[uuid.UUID, set[asyncio.Queue]] = defaultdict(set)

    def subscribe(self, workflow_id: uuid.UUID) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue(maxsize=_MAX_QUEUE)
        self._subs[workflow_id].add(q)
        return q

    def unsubscribe(self, workflow_id: uuid.UUID, q: asyncio.Queue) -> None:
        subs = self._subs.get(workflow_id)
        if subs and q in subs:
            subs.discard(q)
            if not subs:
                self._subs.pop(workflow_id, None)

    def publish(self, workflow_id: uuid.UUID, event: dict[str, Any]) -> None:
        for q in list(self._subs.get(workflow_id, ())):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                logger.warning(
                    "事件总线订阅者消费过慢，事件被丢弃",
                    workflow_id=str(workflow_id),
                    event_type=event.get("event_type"),
                )


_bus_singleton: EventBus | None = None


def get_event_bus() -> EventBus:
    global _bus_singleton
    if _bus_singleton is None:
        _bus_singleton = EventBus()
    return _bus_singleton


def set_event_bus(bus: EventBus) -> None:
    global _bus_singleton
    _bus_singleton = bus


PENDING_EVENTS_KEY = "pending_events"


# 自动捕获：session 每次 flush 时，扫所有新建的 WorkflowEvent，登记到
# pending_events；Database.session() commit 后会 publish 到 bus。
# 这避免了 service 层重复写入 `defer_event(...)`。
from sqlalchemy import event as sa_event  # noqa: E402
from sqlalchemy.orm import Session as SyncSession  # noqa: E402


@sa_event.listens_for(SyncSession, "after_flush")
def _collect_workflow_events(session: SyncSession, flush_context: Any) -> None:
    from scheduler.storage.models import WorkflowEvent  # noqa: PLC0415 — 避免循环 import

    pending = session.info.setdefault(PENDING_EVENTS_KEY, [])
    for obj in session.new:
        if isinstance(obj, WorkflowEvent):
            pending.append(
                {
                    "workflow_id": obj.workflow_id,
                    "event_type": obj.event_type,
                    "payload": obj.payload,
                    "request_id": obj.request_id,
                }
            )
