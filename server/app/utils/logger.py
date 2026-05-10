"""
Structured JSON logging via structlog.

Log format (JSON, production):
{
  "timestamp": "2026-05-08T12:30:45.123Z",
  "level": "INFO",
  "service": "news-analyzer-server",
  "environment": "prod",
  "event": "collection.job.finished",   ← first positional arg to logger.info()
  "message": "...",                      ← optional human-readable kwarg
  ...domain fields...
}

Usage:
    from app.utils.logger import get_logger
    from app.utils.log_events import Events

    logger = get_logger(__name__)
    logger.info(Events.COLLECTION_JOB_FINISHED, message="Done", job_id=42, duration_ms=500)

Secrets masking:
    Any field whose key contains a masked keyword (token, password, secret,
    session, cookie, authorization, api_key, credential) has its value replaced
    with "***MASKED***" or a partial reveal for long strings.
"""
from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
import structlog.contextvars

_SERVICE_NAME = "news-analyzer-server"

# Keys whose values must be masked (case-insensitive substring match)
_SENSITIVE_KEYS = frozenset(
    {
        "token",
        "password",
        "secret",
        "session",
        "cookie",
        "authorization",
        "api_key",
        "apikey",
        "credential",
        "access_token",
        "refresh_token",
        "session_string",
        "passwd",
        "auth",
    }
)


def _is_sensitive(key: str) -> bool:
    key_lower = key.lower()
    return any(s in key_lower for s in _SENSITIVE_KEYS)


def _mask_value(value: Any) -> str:
    if not isinstance(value, str):
        return "***MASKED***"
    if len(value) > 12:
        return f"{value[:4]}***{value[-4:]}"
    return "***MASKED***"


def _mask_dict(d: dict) -> dict:
    out = {}
    for k, v in d.items():
        if _is_sensitive(k):
            out[k] = _mask_value(v)
        elif isinstance(v, dict):
            out[k] = _mask_dict(v)
        elif isinstance(v, list):
            out[k] = [_mask_dict(i) if isinstance(i, dict) else i for i in v]
        else:
            out[k] = v
    return out


# ── Custom processors ──────────────────────────────────────────────────────


def _mask_secrets_processor(
    logger: Any, method: str, event_dict: dict
) -> dict:
    return _mask_dict(event_dict)


def _add_service_context_processor(
    logger: Any, method: str, event_dict: dict
) -> dict:
    from app.core.config import get_settings

    settings = get_settings()
    event_dict.setdefault("service", _SERVICE_NAME)
    event_dict.setdefault("environment", settings.app_env)
    return event_dict


def _rename_level_to_uppercase(
    logger: Any, method: str, event_dict: dict
) -> dict:
    if "level" in event_dict:
        event_dict["level"] = event_dict["level"].upper()
    return event_dict


def _reorder_keys_processor(
    logger: Any, method: str, event_dict: dict
) -> dict:
    """Bring standard fields to the front for readability in JSON output."""
    priority = [
        "timestamp",
        "level",
        "service",
        "environment",
        "event",
        "message",
        "correlation_id",
        "request_id",
        "job_id",
        "source_id",
        "worker_id",
        "platform",
    ]
    ordered: dict = {}
    for key in priority:
        if key in event_dict:
            ordered[key] = event_dict.pop(key)
    ordered.update(event_dict)
    return ordered


# ── Configuration ──────────────────────────────────────────────────────────


def configure_logging() -> None:
    from app.core.config import get_settings

    settings = get_settings()
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    shared_processors: list[structlog.types.Processor] = [
        structlog.contextvars.merge_contextvars,
        _add_service_context_processor,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        _rename_level_to_uppercase,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
        _mask_secrets_processor,
        _reorder_keys_processor,
    ]

    if settings.is_production:
        renderer: structlog.types.Processor = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=True)

    structlog.configure(
        processors=shared_processors
        + [
            structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
        ],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        foreign_pre_chain=shared_processors,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.handlers = [handler]
    root_logger.setLevel(log_level)

    # Silence overly verbose third-party loggers
    for noisy in ("httpx", "httpcore", "sqlalchemy.engine", "sqlalchemy.pool", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def get_logger(name: str) -> structlog.stdlib.BoundLogger:
    return structlog.get_logger(name)
