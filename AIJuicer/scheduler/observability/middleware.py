"""HTTP middleware: X-Request-ID 沿用或生成，并绑定到 contextvar。"""

from __future__ import annotations

import secrets

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response
from starlette.types import ASGIApp

from scheduler.observability.logging import bind_request_id, reset_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    HEADER = "X-Request-ID"

    def __init__(self, app: ASGIApp) -> None:
        super().__init__(app)

    async def dispatch(self, request: Request, call_next):
        rid = request.headers.get(self.HEADER)
        if not rid:
            rid = "req_" + secrets.token_hex(4)
        token = bind_request_id(rid)
        try:
            response: Response = await call_next(request)
            response.headers[self.HEADER] = rid
            return response
        finally:
            reset_request_id(token)
