"""/api/agents endpoints。

在线状态由 Redis presence key 持有（由 Agent SDK 周期性续期）。
- POST /api/agents/register  —— 服务端为新 Agent 分配 id，写一次 Redis presence key。
- GET  /api/agents           —— 直接 SCAN Redis，只返回当前在线的 Agent。

不再维护 `agents` Postgres 表作为在线名册——Postgres 不能自动过期，无法表达
"漏 3 次心跳就消失"的语义。该表保留做向前兼容（不再写入），可在迁移中删除。
"""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException

from scheduler.api import get_database
from scheduler.api.schemas import AgentRead, AgentRegisterRequest, AgentRegisterResponse
from scheduler.config import Settings, get_settings
from scheduler.observability import metrics
from scheduler.observability.logging import get_logger
from scheduler.storage.agent_presence import list_online, set_presence
from scheduler.storage.db import Database
from scheduler.storage.redis_queue import RedisTaskQueue

logger = get_logger(__name__)
router = APIRouter(prefix="/api/agents", tags=["agents"])


def _redis_client(db: Database):
    tq = db.task_queue
    if not isinstance(tq, RedisTaskQueue):
        raise HTTPException(status_code=503, detail="redis presence unavailable")
    return tq.client


@router.post("/register", response_model=AgentRegisterResponse)
async def register_agent(
    body: AgentRegisterRequest,
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> AgentRegisterResponse:
    redis = _redis_client(db)
    agent_id = str(uuid.uuid4())
    await set_presence(
        redis,
        agent_id=agent_id,
        name=body.name,
        step=body.step,
        ttl_sec=settings.presence_ttl_sec,
        metadata=body.metadata or {},
    )
    metrics.agents_online.labels(step=body.step).inc()
    md = body.metadata or {}
    logger.info(
        "Agent 注册成功",
        agent_id=agent_id,
        name=body.name,
        step=body.step,
        host=md.get("host"),
        port=md.get("port"),
        ttl_sec=settings.presence_ttl_sec,
    )
    # 直接构造响应；DB 不再参与
    from datetime import UTC, datetime  # noqa: PLC0415

    return AgentRegisterResponse(
        id=uuid.UUID(agent_id),
        name=body.name,
        step=body.step,
        status="online",
        last_seen_at=datetime.now(UTC),
        host=md.get("host"),
        port=md.get("port"),
        pid=md.get("pid"),
        hostname=md.get("hostname"),
        redis_url=settings.redis_url,
    )


@router.get("", response_model=list[AgentRead])
async def list_agents(
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> list[AgentRead]:
    """列出所有当前 presence key 还活着的 Agent。

    last_seen_at 距 now 超过 `heartbeat_interval_sec` → 标记 status=offline 但仍返回。
    超过 `presence_ttl_sec`（默认 3 ×）的 Agent 已被 Redis 自动过期，不会出现在结果里。
    """
    from datetime import UTC, datetime  # noqa: PLC0415

    redis = _redis_client(db)
    items = await list_online(redis)
    now = datetime.now(UTC)
    threshold = settings.heartbeat_interval_sec
    result: list[AgentRead] = []
    for it in items:
        try:
            md = it.get("metadata") or {}
            last_seen = _parse_iso(it["last_seen_at"])
            age_sec = (now - last_seen).total_seconds()
            status = "offline" if age_sec > threshold else it.get("status", "online")
            result.append(
                AgentRead(
                    id=uuid.UUID(it["id"]),
                    name=it["name"],
                    step=it["step"],
                    status=status,
                    last_seen_at=last_seen,
                    host=md.get("host"),
                    port=md.get("port"),
                    pid=md.get("pid"),
                    hostname=md.get("hostname"),
                )
            )
        except (KeyError, ValueError) as e:
            logger.warning("跳过解析失败的 Agent presence 记录", error=str(e))
    logger.info("查询在线 Agent 列表", count=len(result), threshold_sec=threshold)
    return result


def _parse_iso(s: str):
    from datetime import datetime  # noqa: PLC0415

    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    return datetime.fromisoformat(s)


@router.post("/{agent_id}/heartbeat", status_code=204)
async def heartbeat_agent(
    agent_id: str,
    body: AgentRegisterRequest,
    db: Database = Depends(get_database),
    settings: Settings = Depends(get_settings),
) -> None:
    """Agent SDK 周期性调用：续期 presence TTL。

    复用 register 的请求体（name + step + metadata），由 Agent 自己保留 id。
    """
    redis = _redis_client(db)
    await set_presence(
        redis,
        agent_id=agent_id,
        name=body.name,
        step=body.step,
        ttl_sec=settings.presence_ttl_sec,
        metadata=body.metadata or {},
    )
