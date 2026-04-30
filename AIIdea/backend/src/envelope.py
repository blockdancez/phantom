"""Unified response envelope for all /api endpoints.

The contract:

    { "code": "000000", "message": "success", "data": {...}, "request_id": "..." }

``EnvelopeMiddleware`` reads the JSON body produced by handlers and wraps it
if it is not already wrapped. Exception handlers for ``APIError``,
``HTTPException``, ``RequestValidationError`` and ``Exception`` build the
same envelope directly, so every path — success or failure — returns an
identical shape.
"""

from __future__ import annotations

import json
from typing import Any

import structlog
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from src.exceptions import APIError, ErrorCode

logger = structlog.get_logger()


def _request_id(request: Request) -> str:
    rid = getattr(request.state, "request_id", None)
    if isinstance(rid, str) and rid:
        return rid
    return ""


def envelope(
    code: str,
    message: str,
    data: Any,
    request_id: str,
) -> dict[str, Any]:
    return {
        "code": code,
        "message": message,
        "data": data,
        "request_id": request_id,
    }


def make_response(
    data: Any,
    request_id: str,
    *,
    code: str = ErrorCode.SUCCESS,
    message: str = "success",
    http_status: int = 200,
) -> JSONResponse:
    body = envelope(code, message, data, request_id)
    headers = {"x-request-id": request_id} if request_id else {}
    return JSONResponse(body, status_code=http_status, headers=headers)


class EnvelopeMiddleware(BaseHTTPMiddleware):
    """Wrap successful JSON responses from /api routes.

    We only rewrite JSON responses whose bodies aren't already shaped like
    the envelope. Exception handlers produce envelopes directly and
    non-JSON or streaming responses (docs, redirects) are passed through.

    ``BaseHTTPMiddleware`` intercepts exceptions thrown by downstream
    middleware/routes in a way that prevents FastAPI's generic ``Exception``
    handler from firing. To preserve that contract we catch anything that
    is not already an ``HTTPException`` (those still go through the normal
    handler path) and produce the 500 envelope ourselves.
    """

    async def dispatch(self, request: Request, call_next):
        try:
            response: Response = await call_next(request)
        except StarletteHTTPException:
            raise
        except Exception as exc:
            logger.error(
                "未处理异常",
                error_type=type(exc).__name__,
                error=str(exc),
                exc_info=True,
            )
            request_id = _request_id(request)
            return make_response(
                None,
                request_id,
                code=ErrorCode.INTERNAL,
                message="internal server error",
                http_status=500,
            )

        if not request.url.path.startswith("/api"):
            return response

        media_type = (response.headers.get("content-type") or "").split(";")[0].strip()
        if media_type != "application/json":
            return response

        body = b""
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            body += chunk

        try:
            data: Any = json.loads(body) if body else None
        except json.JSONDecodeError:
            return Response(
                content=body,
                status_code=response.status_code,
                media_type=media_type,
                headers=dict(response.headers),
            )

        if isinstance(data, dict) and {"code", "message", "request_id"}.issubset(
            data.keys()
        ):
            headers = dict(response.headers)
            headers.pop("content-length", None)
            return JSONResponse(
                data, status_code=response.status_code, headers=headers
            )

        request_id = _request_id(request)
        wrapped = envelope(ErrorCode.SUCCESS, "success", data, request_id)
        headers = dict(response.headers)
        headers.pop("content-length", None)
        headers["x-request-id"] = request_id
        return JSONResponse(wrapped, status_code=response.status_code, headers=headers)


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(APIError)
    async def _api_error_handler(request: Request, exc: APIError) -> JSONResponse:
        request_id = _request_id(request)
        logger.info(
            "接口错误",
            code=exc.code,
            http_status=exc.http_status,
            message=exc.message,
        )
        return make_response(
            exc.data,
            request_id,
            code=exc.code,
            message=exc.message,
            http_status=exc.http_status,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_handler(
        request: Request, exc: RequestValidationError
    ) -> JSONResponse:
        request_id = _request_id(request)
        errors = [
            {
                "field": ".".join(str(p) for p in err.get("loc", ())),
                "message": err.get("msg", ""),
                "type": err.get("type", ""),
            }
            for err in exc.errors()
        ]
        logger.info("参数校验失败", errors=errors)
        return make_response(
            {"errors": errors},
            request_id,
            code=ErrorCode.BAD_REQUEST,
            message="invalid request parameters",
            http_status=400,
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_exception_handler(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        request_id = _request_id(request)
        code = {
            400: ErrorCode.BAD_REQUEST,
            404: ErrorCode.NOT_FOUND,
            405: ErrorCode.METHOD_NOT_ALLOWED,
            503: ErrorCode.SERVICE_UNAVAILABLE,
        }.get(exc.status_code, f"HTTP{exc.status_code:03d}")
        message = exc.detail if isinstance(exc.detail, str) else "error"
        logger.info(
            "http_exception", status_code=exc.status_code, detail=message
        )
        return make_response(
            None,
            request_id,
            code=code,
            message=message,
            http_status=exc.status_code,
        )

    @app.exception_handler(Exception)
    async def _catch_all_handler(request: Request, exc: Exception) -> JSONResponse:
        request_id = _request_id(request)
        logger.error(
            "未处理异常",
            error_type=type(exc).__name__,
            error=str(exc),
            exc_info=True,
        )
        return make_response(
            None,
            request_id,
            code=ErrorCode.INTERNAL,
            message="internal server error",
            http_status=500,
        )
