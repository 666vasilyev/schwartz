"""
Structured log context helpers.
Wraps structlog.contextvars so callers don't import structlog directly.

Usage:
    set_request_context(request_id="req_abc", correlation_id="corr_xyz")
    set_job_context(job_id=42, source_id=7, worker_id="host:pid:uid")
    clear_context()         # call in middleware finally-block
"""
from __future__ import annotations

import structlog.contextvars


def set_request_context(
    *,
    request_id: str | None = None,
    correlation_id: str | None = None,
) -> None:
    ctx: dict = {}
    if request_id:
        ctx["request_id"] = request_id
    if correlation_id:
        ctx["correlation_id"] = correlation_id
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def set_job_context(
    *,
    job_id: int | None = None,
    source_id: int | None = None,
    worker_id: str | None = None,
    platform: str | None = None,
    correlation_id: str | None = None,
) -> None:
    ctx: dict = {}
    if job_id is not None:
        ctx["job_id"] = job_id
    if source_id is not None:
        ctx["source_id"] = source_id
    if worker_id:
        ctx["worker_id"] = worker_id
    if platform:
        ctx["platform"] = platform
    if correlation_id:
        ctx["correlation_id"] = correlation_id
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def set_source_context(
    *,
    source_id: int | None = None,
    platform: str | None = None,
) -> None:
    ctx: dict = {}
    if source_id is not None:
        ctx["source_id"] = source_id
    if platform:
        ctx["platform"] = platform
    if ctx:
        structlog.contextvars.bind_contextvars(**ctx)


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()


def bind(**kwargs: object) -> None:
    """Bind arbitrary key-value pairs into the current log context."""
    filtered = {k: v for k, v in kwargs.items() if v is not None}
    if filtered:
        structlog.contextvars.bind_contextvars(**filtered)
