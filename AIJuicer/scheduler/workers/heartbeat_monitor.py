"""心跳超时监控（spec § 4.2D）。

每 interval 秒扫一次 status='running' AND last_heartbeat_at < now()-timeout 的
step_executions，对每条调 TaskService.fail(retryable=True)，复用现有的
"重试到 max_retries 否则转 AWAITING_MANUAL_ACTION" 分支。
"""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from scheduler.engine.task_service import TaskService
from scheduler.observability import metrics
from scheduler.observability.logging import get_logger
from scheduler.storage.db import Database
from scheduler.storage.models import StepExecution

logger = get_logger(__name__)


async def scan_once(
    database: Database,
    *,
    timeout_sec: int,
    max_retries: int,
) -> int:
    """单次扫描 + 处理，返回判定为超时的 step 数。"""
    cutoff = datetime.now(UTC) - timedelta(seconds=timeout_sec)
    async with database.session() as session:
        result = await session.execute(
            select(StepExecution)
            .where(StepExecution.status == "running")
            .where(StepExecution.last_heartbeat_at < cutoff)
        )
        stale = list(result.scalars().all())
        if not stale:
            return 0
        svc = TaskService(session, max_retries=max_retries)
        for step in stale:
            metrics.heartbeat_timeout_total.labels(step=step.step).inc()
            logger.warning(
                "任务心跳超时",
                task_id=str(step.id),
                workflow_id=str(step.workflow_id),
                step=step.step,
                attempt=step.attempt,
                last_heartbeat_at=step.last_heartbeat_at.isoformat()
                if step.last_heartbeat_at
                else None,
            )
            await svc.fail(
                task_id=step.id,
                error=f"heartbeat timeout > {timeout_sec}s",
                retryable=True,
                request_id=step.request_id,
            )
    return len(stale)


async def run_monitor(
    database: Database,
    *,
    interval_sec: int,
    timeout_sec: int,
    max_retries: int,
    stop_event: asyncio.Event | None = None,
) -> None:
    """阻塞循环：每 interval 扫一次直到 stop_event 触发或被 cancel。"""
    stop_event = stop_event or asyncio.Event()
    logger.info(
        "心跳监控启动",
        interval_sec=interval_sec,
        timeout_sec=timeout_sec,
    )
    try:
        while not stop_event.is_set():
            try:
                n = await scan_once(database, timeout_sec=timeout_sec, max_retries=max_retries)
                if n:
                    logger.info("心跳监控本轮扫描完成", timed_out=n)
            except Exception as exc:  # noqa: BLE001 — 扫描失败不应停掉 monitor
                logger.error("心跳监控扫描异常", error=str(exc))
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_sec)
            except TimeoutError:
                continue
    finally:
        logger.info("心跳监控已停止")
