import structlog
from fastapi import APIRouter, Request
from sqlalchemy import text

from src.db import get_async_session_factory
from src.exceptions import APIError, ErrorCode

router = APIRouter()
logger = structlog.get_logger()


async def _check_db() -> bool:
    factory = get_async_session_factory()
    async with factory() as session:
        await session.execute(text("SELECT 1"))
    return True


@router.get("/health")
async def health(request: Request) -> dict:
    logger.info("健康检查")

    db_status = "ok"
    db_ok = False
    try:
        await _check_db()
        db_ok = True
    except Exception as exc:
        logger.error("数据库健康检查失败", error_type=type(exc).__name__, error=str(exc))
        db_status = "fail"

    scheduler = getattr(request.app.state, "scheduler", None)
    scheduler_status = "ok" if (scheduler is not None and scheduler.running) else "fail"

    data = {
        "status": "ok" if (db_ok and scheduler_status == "ok") else "fail",
        "db": db_status,
        "scheduler": scheduler_status,
    }

    if not db_ok:
        # Per plan: DB unreachable returns 503 + structured error while still
        # exposing the sub-status bits in data.
        raise APIError(
            code=ErrorCode.HEALTH_DB_FAIL,
            message="database not reachable",
            http_status=503,
            data=data,
        )
    return data
