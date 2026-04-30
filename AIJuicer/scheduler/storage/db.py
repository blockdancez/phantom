"""异步 DB 引擎 + session factory。

session() context manager 承载"DB commit 后 XADD 到 Redis Streams"的保证
（spec § 3.4）：service 只往 session.info['pending_xadds'] 追加 (step, payload)，
这里统一在 commit 成功后再批量 XADD。commit 失败 / 抛异常时 payload 直接丢弃。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from scheduler.config import Settings
from scheduler.observability.logging import get_logger
from scheduler.storage.redis_queue import TaskQueue

logger = get_logger(__name__)

PENDING_XADDS_KEY = "pending_xadds"


def defer_xadd(session: AsyncSession, step: str, payload: dict) -> None:
    """service 层调用：登记一个"commit 后才 XADD"的任务。"""
    pending = session.info.setdefault(PENDING_XADDS_KEY, [])
    pending.append((step, payload))


class Database:
    def __init__(self, settings: Settings, *, task_queue: TaskQueue | None = None) -> None:
        self._engine: AsyncEngine = create_async_engine(
            settings.database_url,
            echo=False,
            pool_pre_ping=True,
            pool_size=10,
            max_overflow=5,
        )
        self._session_factory = async_sessionmaker(
            bind=self._engine,
            expire_on_commit=False,
            class_=AsyncSession,
        )
        self._task_queue = task_queue

    @property
    def engine(self) -> AsyncEngine:
        return self._engine

    @property
    def task_queue(self) -> TaskQueue | None:
        return self._task_queue

    def set_task_queue(self, tq: TaskQueue | None) -> None:
        self._task_queue = tq

    @asynccontextmanager
    async def session(self) -> AsyncIterator[AsyncSession]:
        from scheduler.engine.event_bus import PENDING_EVENTS_KEY, get_event_bus

        session = self._session_factory()
        session.info[PENDING_XADDS_KEY] = []
        session.info[PENDING_EVENTS_KEY] = []
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        else:
            # DB 已 commit 成功 → 先发 event（SSE 订阅者），再 XADD（agent 拉任务）。
            pending_events: list[dict] = session.info.get(PENDING_EVENTS_KEY, [])
            if pending_events:
                bus = get_event_bus()
                for ev in pending_events:
                    bus.publish(ev["workflow_id"], ev)

            pending: list[tuple[str, dict]] = session.info.get(PENDING_XADDS_KEY, [])
            if pending and self._task_queue is not None:
                for step, payload in pending:
                    try:
                        await self._task_queue.xadd(step, payload)
                    except Exception as exc:  # noqa: BLE001 — 队列不可用不应 crash 请求
                        logger.error(
                            "任务写入 Redis Stream 失败",
                            step=step,
                            task_id=payload.get("task_id"),
                            error=str(exc),
                        )
        finally:
            await session.close()

    async def dispose(self) -> None:
        await self._engine.dispose()
