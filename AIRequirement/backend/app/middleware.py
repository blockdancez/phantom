import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.logging_setup import generate_request_id

logger = structlog.get_logger()


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = request.headers.get("X-Request-ID", generate_request_id())
        request.state.request_id = request_id

        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(request_id=request_id)

        logger.info(
            "收到请求",
            method=request.method,
            path=str(request.url.path),
        )

        response = await call_next(request)

        logger.info(
            "请求完成",
            method=request.method,
            path=str(request.url.path),
            status_code=response.status_code,
        )

        response.headers["X-Request-ID"] = request_id
        return response
