"""Redis Streams 任务队列抽象与实现（spec § 3.3）。

每个 step 一条 stream：tasks:<step>，每条 stream 对应一个 consumer group agents:<step>。
scheduler 只负责 XADD（生产者），消费由 agent SDK 的 XREADGROUP 完成。
"""

from __future__ import annotations

import json
from typing import Protocol

import redis.asyncio as redis_async
from redis.exceptions import ResponseError

from scheduler.engine.state_machine import STEPS
from scheduler.observability.logging import get_logger

logger = get_logger(__name__)


def stream_key(step: str) -> str:
    return f"tasks:{step}"


def consumer_group(step: str) -> str:
    return f"agents:{step}"


class TaskQueue(Protocol):
    """scheduler 视角的任务队列接口。"""

    async def xadd(self, step: str, payload: dict) -> str: ...

    async def ensure_consumer_groups(self) -> None: ...

    async def purge_workflow(self, workflow_id: str) -> dict[str, int]: ...

    async def close(self) -> None: ...


class RedisTaskQueue:
    """真实 Redis Streams 实现。"""

    def __init__(self, redis_url: str) -> None:
        self._client: redis_async.Redis = redis_async.from_url(redis_url, decode_responses=True)

    @property
    def client(self) -> redis_async.Redis:
        """暴露底层 redis 客户端，给 presence / 其他模块复用。"""
        return self._client

    async def xadd(self, step: str, payload: dict) -> str:
        # Stream 字段必须是平坦的 str→str；整个任务 payload JSON 编码后放在单字段 data 里
        message_id: str = await self._client.xadd(
            stream_key(step), {"data": json.dumps(payload, default=str)}
        )
        logger.info(
            "任务已写入 Redis Stream",
            step=step,
            task_id=payload.get("task_id"),
            workflow_id=payload.get("workflow_id"),
            message_id=message_id,
        )
        return message_id

    async def ensure_consumer_groups(self) -> None:
        """为每个 step 的 stream 建一次 consumer group（BUSYGROUP 视为已建）。"""
        for step in STEPS:
            try:
                await self._client.xgroup_create(
                    name=stream_key(step),
                    groupname=consumer_group(step),
                    id="$",
                    mkstream=True,
                )
                logger.info("创建 Redis 消费者组", step=step, group=consumer_group(step))
            except ResponseError as e:
                if "BUSYGROUP" in str(e):
                    continue
                raise

    async def purge_workflow(self, workflow_id: str) -> dict[str, int]:
        """删除工作流时清理它在 Redis Streams 里的残留。

        遍历 6 个 step 的 stream，找出 payload.workflow_id 命中的条目，
        XACK（防止留在 pending）+ XDEL（从 stream 删掉）。
        返回 {step: 删除条数}。
        """
        deleted: dict[str, int] = {}
        for step in STEPS:
            sk = stream_key(step)
            cg = consumer_group(step)
            try:
                entries = await self._client.xrange(sk, count=10000)
            except ResponseError:
                deleted[step] = 0
                continue
            ids_to_delete: list[str] = []
            for msg_id, fields in entries:
                raw = fields.get("data") if isinstance(fields, dict) else None
                if not raw:
                    continue
                try:
                    payload = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue
                if payload.get("workflow_id") == workflow_id:
                    ids_to_delete.append(msg_id)
            if ids_to_delete:
                try:
                    await self._client.xack(sk, cg, *ids_to_delete)
                except ResponseError:
                    pass
                await self._client.xdel(sk, *ids_to_delete)
            deleted[step] = len(ids_to_delete)
        return deleted

    async def close(self) -> None:
        await self._client.aclose()


class InMemoryTaskQueue:
    """测试用内存实现；保留 (step, payload) 列表。"""

    def __init__(self) -> None:
        self.enqueued: list[tuple[str, dict]] = []
        self._counter = 0

    async def xadd(self, step: str, payload: dict) -> str:
        self._counter += 1
        self.enqueued.append((step, payload))
        return f"0-{self._counter}"

    async def ensure_consumer_groups(self) -> None:
        return None

    async def purge_workflow(self, workflow_id: str) -> dict[str, int]:
        before = len(self.enqueued)
        self.enqueued = [(s, p) for s, p in self.enqueued if p.get("workflow_id") != workflow_id]
        return {"_total": before - len(self.enqueued)}

    async def close(self) -> None:
        return None

    def pop_all(self) -> list[tuple[str, dict]]:
        items = list(self.enqueued)
        self.enqueued.clear()
        return items
