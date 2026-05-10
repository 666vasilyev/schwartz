"""
Request logging middleware.

Injects request_id (X-Request-ID or generated) and correlation_id
(X-Correlation-ID or request_id) into the structlog context for every request,
then emits http.request.started / http.request.finished with duration_ms.

Response always carries X-Request-ID so callers can correlate logs.
"""
from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.utils.log_context import clear_context, set_request_context
from app.utils.log_events import Events
from app.utils.logger import get_logger

logger = get_logger(__name__)

_SKIP_PATHS = frozenset({"/health", "/docs", "/redoc", "/openapi.json"})


class RequestLoggingMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self,
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        path = request.url.path
        if path in _SKIP_PATHS:
            return await call_next(request)

        request_id = request.headers.get("X-Request-ID") or f"req_{uuid.uuid4().hex[:10]}"
        correlation_id = request.headers.get("X-Correlation-ID") or request_id

        set_request_context(request_id=request_id, correlation_id=correlation_id)
        start = time.perf_counter()

        logger.info(
            Events.HTTP_REQUEST_STARTED,
            message=f"{request.method} {path}",
            method=request.method,
            path=path,
            query=str(request.url.query) or None,
            client_ip=_client_ip(request),
        )

        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        except Exception as exc:
            duration_ms = int((time.perf_counter() - start) * 1000)
            logger.error(
                Events.HTTP_REQUEST_ERROR,
                message=f"{request.method} {path} → unhandled error",
                method=request.method,
                path=path,
                error=str(exc),
                duration_ms=duration_ms,
            )
            raise
        finally:
            duration_ms = int((time.perf_counter() - start) * 1000)
            _log_finished(request.method, path, status_code, duration_ms)
            response_obj = locals().get("response")
            if response_obj is not None:
                response_obj.headers["X-Request-ID"] = request_id
            clear_context()


def _log_finished(method: str, path: str, status_code: int, duration_ms: int) -> None:
    log_fn = logger.warning if status_code >= 400 else logger.info
    log_fn(
        Events.HTTP_REQUEST_FINISHED,
        message=f"{method} {path} → {status_code}",
        method=method,
        path=path,
        status_code=status_code,
        duration_ms=duration_ms,
    )


def _client_ip(request: Request) -> str | None:
    forwarded_for = request.headers.get("X-Forwarded-For")
    if forwarded_for:
        return forwarded_for.split(",")[0].strip()
    if request.client:
        return request.client.host
    return None
