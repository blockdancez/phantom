"""/api/system endpoints —— Redis 连接信息 + 每个 step 的队列深度 / 消费者状态。

供 webui 系统状态页使用，也可以给 ops 直接打开浏览器看。
"""

from __future__ import annotations

import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from scheduler.api import get_database
from scheduler.config import Settings, get_settings
from scheduler.engine.state_machine import STEPS
from scheduler.observability.logging import get_logger
from scheduler.storage.agent_presence import count_online_for_step
from scheduler.storage.db import Database
from scheduler.storage.redis_queue import RedisTaskQueue, consumer_group, stream_key

logger = get_logger(__name__)
router = APIRouter(prefix="/api/system", tags=["system"])


def _redis_client(db: Database):
    tq = db.task_queue
    if not isinstance(tq, RedisTaskQueue):
        raise HTTPException(status_code=503, detail="redis presence unavailable")
    return tq.client


def _redact_redis_url(url: str) -> str:
    """隐藏密码，避免在 UI 上暴露：redis://user:pass@host:port/db → redis://user:***@host:port/db"""
    try:
        scheme, rest = url.split("://", 1)
        if "@" in rest:
            cred, host = rest.split("@", 1)
            if ":" in cred:
                user, _ = cred.split(":", 1)
                cred = f"{user}:***"
            rest = f"{cred}@{host}"
        return f"{scheme}://{rest}"
    except Exception:  # noqa: BLE001
        return url


@router.get("/status")
async def system_status(
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> dict[str, Any]:
    redis = _redis_client(db)

    # ── Redis 自身 ──
    t0 = time.perf_counter()
    pong = await redis.ping()
    ping_ms = round((time.perf_counter() - t0) * 1000, 2)
    info = await redis.info()
    redis_block = {
        "url": _redact_redis_url(settings.redis_url),
        "ping": bool(pong),
        "ping_ms": ping_ms,
        "version": info.get("redis_version"),
        "mode": info.get("redis_mode"),
        "uptime_sec": info.get("uptime_in_seconds"),
        "used_memory_human": info.get("used_memory_human"),
        "connected_clients": info.get("connected_clients"),
        "total_commands_processed": info.get("total_commands_processed"),
    }

    # ── 每个 step 的 stream / consumer group / 在线 agent ──
    steps_block: list[dict[str, Any]] = []
    for step in STEPS:
        sk = stream_key(step)
        cg = consumer_group(step)
        try:
            length = await redis.xlen(sk)
        except Exception:  # noqa: BLE001 — stream 可能还不存在
            length = 0

        pending_total = 0
        consumers_info: list[dict[str, Any]] = []
        # Redis Streams 不会自动清理"换了 pid 的旧消费者"，会无限累积。idle 超过这个
        # 阈值就视为僵尸，不展示在 UI 上；同时如果它没有未确认消息，顺手 reap 掉。
        STALE_IDLE_MS = 5 * 60 * 1000  # 5 分钟
        try:
            pending_summary = await redis.xpending(sk, cg)
            # xpending 返回 dict: {pending, min, max, consumers}
            if isinstance(pending_summary, dict):
                pending_total = int(pending_summary.get("pending") or 0)
            consumers_raw = await redis.xinfo_consumers(sk, cg)
            for c in consumers_raw or []:
                idle_ms = int(c.get("idle") or 0)
                pending = int(c.get("pending") or 0)
                if idle_ms > STALE_IDLE_MS:
                    # 顺手 reap：仅在没有未确认消息时删；有 pending 留给 scheduler
                    # startup recovery 处理，避免丢任务
                    if pending == 0:
                        try:
                            await redis.xgroup_delconsumer(sk, cg, c.get("name"))
                        except Exception:  # noqa: BLE001
                            pass
                    continue
                consumers_info.append(
                    {
                        "name": c.get("name"),
                        "pending": pending,
                        "idle_ms": idle_ms,
                    }
                )
        except Exception:  # noqa: BLE001 — group 还没建好
            pass

        agents_online = await count_online_for_step(redis, step=step)

        steps_block.append(
            {
                "step": step,
                "stream": sk,
                "group": cg,
                "stream_length": int(length),
                "pending": pending_total,
                "consumers": consumers_info,
                "agents_online": agents_online,
            }
        )

    return {"redis": redis_block, "steps": steps_block}
