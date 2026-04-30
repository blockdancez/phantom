"""Redis-backed agent presence registry。

设计：每个在线 Agent 在 Redis 里持有一个带 TTL 的 key
`agent:<step>:<agent_id>`，由 Agent SDK 周期性 SET（续 TTL）。
TTL = 3 × heartbeat_interval（默认 90s）：
- 漏 1 次心跳 → key 仍在但 last_seen_at 已陈旧（用于"停止派发"判断）
- 漏 3 次心跳 → key 自动过期 → 列表里消失（=自动下线）

scheduler 不主动写续期，只在 register / list / 派发预检 时读取。
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

import redis.asyncio as redis_async

from scheduler.observability.logging import get_logger

logger = get_logger(__name__)


def presence_key(step: str, agent_id: str) -> str:
    return f"agent:{step}:{agent_id}"


def _scan_pattern(step: str | None = None) -> str:
    return f"agent:{step}:*" if step else "agent:*"


async def set_presence(
    redis: redis_async.Redis,
    *,
    agent_id: str,
    name: str,
    step: str,
    ttl_sec: int,
    metadata: dict | None = None,
) -> None:
    """注册或续期一个 Agent 的在线状态。"""
    payload = {
        "id": agent_id,
        "name": name,
        "step": step,
        "status": "online",
        "last_seen_at": datetime.utcnow().isoformat() + "Z",
        "metadata": metadata or {},
    }
    await redis.set(presence_key(step, agent_id), json.dumps(payload), ex=ttl_sec)


async def delete_presence(redis: redis_async.Redis, *, agent_id: str, step: str) -> None:
    """优雅下线：主动删除 key。"""
    await redis.delete(presence_key(step, agent_id))


async def list_online(redis: redis_async.Redis, *, step: str | None = None) -> list[dict[str, Any]]:
    """SCAN 全部在线 Agent。step=None 时返回所有 step；否则只返回该 step 的。"""
    items: list[dict[str, Any]] = []
    keys: list[str] = []
    async for key in redis.scan_iter(match=_scan_pattern(step), count=200):
        keys.append(key if isinstance(key, str) else key.decode())
    if not keys:
        return items
    raw_values = await redis.mget(keys)
    for raw in raw_values:
        if raw is None:
            continue
        try:
            items.append(json.loads(raw))
        except (json.JSONDecodeError, TypeError):
            logger.warning("Agent presence 记录格式异常，跳过", raw=str(raw)[:200])
    items.sort(key=lambda a: a.get("last_seen_at", ""), reverse=True)
    return items


async def has_online_for_step(redis: redis_async.Redis, *, step: str) -> bool:
    """快速判断该 step 是否有任意一个在线 Agent。"""
    async for _ in redis.scan_iter(match=_scan_pattern(step), count=50):
        return True
    return False


async def count_online_for_step(redis: redis_async.Redis, *, step: str) -> int:
    """该 step 当前在线 Agent 数量。"""
    n = 0
    async for _ in redis.scan_iter(match=_scan_pattern(step), count=200):
        n += 1
    return n
