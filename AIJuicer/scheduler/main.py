"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from scheduler.api import set_database
from scheduler.api.agents import router as agents_router
from scheduler.api.approvals import router as approvals_router
from scheduler.api.artifacts import router as artifacts_router
from scheduler.api.dashboard import router as dashboard_router
from scheduler.api.events import router as events_router
from scheduler.api.system import router as system_router
from scheduler.api.tasks import router as tasks_router
from scheduler.api.workflows import router as workflows_router
from scheduler.config import get_settings
from scheduler.engine.recovery import run_startup_recovery
from scheduler.observability import metrics
from scheduler.observability.logging import configure_logging, get_logger
from scheduler.observability.middleware import RequestIdMiddleware
from scheduler.storage.db import Database
from scheduler.storage.redis_queue import RedisTaskQueue
from scheduler.workers.heartbeat_monitor import run_monitor


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(
        level=settings.log_level,
        format=settings.log_format,
        log_file=settings.log_file,
    )
    logger = get_logger(__name__)

    task_queue = RedisTaskQueue(settings.redis_url)
    database = Database(settings, task_queue=task_queue)
    set_database(database)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("调度器启动中", redis_url=settings.redis_url)
        await task_queue.ensure_consumer_groups()
        await run_startup_recovery(database)

        monitor_stop = asyncio.Event()
        monitor_task = asyncio.create_task(
            run_monitor(
                database,
                interval_sec=settings.heartbeat_interval_sec // 2 or 15,
                timeout_sec=settings.heartbeat_timeout_sec,
                max_retries=settings.max_retries,
                stop_event=monitor_stop,
            )
        )

        try:
            yield
        finally:
            monitor_stop.set()
            monitor_task.cancel()
            try:
                await monitor_task
            except asyncio.CancelledError:
                pass
            await task_queue.close()
            await database.dispose()
            logger.info("调度器已停止")

    app = FastAPI(
        title="AI 榨汁机 · 调度器",
        version="0.1.0",
        lifespan=lifespan,
    )
    # CORS：前端 Next.js 本地 dev 跑在 3000，SSE 也走这里
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestIdMiddleware)
    app.include_router(workflows_router)
    app.include_router(tasks_router)
    app.include_router(approvals_router)
    app.include_router(agents_router)
    app.include_router(artifacts_router)
    app.include_router(events_router)
    app.include_router(system_router)
    app.include_router(dashboard_router)

    @app.get("/health")
    async def health() -> dict:
        return {"status": "ok"}

    @app.get("/metrics")
    async def prometheus_metrics() -> Response:
        body, ctype = metrics.render()
        return Response(content=body, media_type=ctype)

    return app


app = create_app()
