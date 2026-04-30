"""Request-scoped middleware: attach request_id and emit two access lines.

Per backend coding standards (`请求拦截` + `Request ID` + `日志`):

- Every request emits a ``request_started`` (with method/path/query/body)
  and a ``request_completed`` (with status_code/duration_ms/body) at
  INFO level. Bodies >1 KB are truncated.
- ``X-Request-ID`` is taken from the request header; if absent a UUID is
  generated. The id is bound into structlog ``contextvars`` so every
  downstream log line in the same call chain carries it, and is echoed
  back via the ``X-Request-ID`` response header.
- The envelope middleware is responsible for ensuring the JSON body's
  ``request_id`` field carries the same value (see ``src.envelope``).
"""

from __future__ import annotations

import time

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from structlog.contextvars import bind_contextvars, clear_contextvars

from src.logging_setup import generate_request_id

logger = structlog.get_logger()

_BODY_LOG_LIMIT = 1024


def _truncate(data: bytes) -> str:
    if not data:
        return ""
    try:
        text = data.decode("utf-8", errors="replace")
    except Exception:
        text = repr(data[:_BODY_LOG_LIMIT])
    if len(text) <= _BODY_LOG_LIMIT:
        return text
    return text[:_BODY_LOG_LIMIT] + f"...<truncated, total={len(text)}>"


class RequestIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        clear_contextvars()
        request_id = request.headers.get("x-request-id") or generate_request_id()
        bind_contextvars(request_id=request_id)
        request.state.request_id = request_id

        method = request.method
        path = str(request.url.path)

        # Buffer + replay request body so handlers can still read it.
        request_body = await request.body()

        async def _replay_receive():
            return {"type": "http.request", "body": request_body, "more_body": False}

        request = Request(request.scope, _replay_receive)
        request.state.request_id = request_id

        logger.info(
            "请求开始",
            method=method,
            path=path,
            query=str(request.url.query) if request.url.query else "",
            request_body=_truncate(request_body),
        )

        t0 = time.perf_counter()
        response: Response = await call_next(request)
        response.headers["x-request-id"] = request_id

        # Capture response body so we can include it in the access log.
        # Drain body_iterator and re-emit; otherwise StreamingResponse
        # yields nothing on the second iteration.
        response_body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            response_body += chunk

        wrapped = Response(
            content=response_body,
            status_code=response.status_code,
            headers={k: v for k, v in response.headers.items() if k.lower() != "content-length"},
            media_type=response.media_type,
        )

        logger.info(
            "请求结束",
            method=method,
            path=path,
            status_code=response.status_code,
            duration_ms=int((time.perf_counter() - t0) * 1000),
            response_body=_truncate(response_body),
        )
        return wrapped
