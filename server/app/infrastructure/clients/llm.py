"""LLM client facade.

Маршрутизирует вызовы к активному Ollama-провайдеру через llm_registry.
Per-request override: передайте provider= и/или model= для конкретного вызова.
Все ошибки провайдера конвертируются в HTTPException(502).
"""
from __future__ import annotations

import asyncio
import time
from typing import Any

from fastapi import HTTPException, status
from tenacity import RetryError

from app.infrastructure.clients import llm_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Жёсткий потолок на весь вызов (включая все ретраи провайдера), в секундах.
# Провайдер сам таймаутит и ретраит отдельные попытки (см. ollama_provider.py),
# но это не спасает, если соединение "живо" (сервер шлёт байты), а генерация
# просто идёт очень долго — тогда httpx-таймаут по инактивности не сработает.
# Этот wait_for — независимая страховка на уровне приложения.
_REQUEST_TIMEOUT_S = 300.0


def _resolve(provider: str | None, model: str | None):
    if provider is not None:
        p = llm_registry.get_provider(provider)
        if model is None:
            models = llm_registry.MODELS_CATALOG.get(provider, {}).get("models", [])
            model = models[0] if models else provider
        return p, model
    return llm_registry.get_active_provider()


def _unwrap_retry_error(exc: RetryError) -> str:
    try:
        original = exc.last_attempt.exception()
        return f"{type(original).__name__}: {str(original)[:300]}"
    except Exception:
        return str(exc)


def _to_http_502(exc: Exception, provider: str, model: str) -> HTTPException:
    if isinstance(exc, RetryError):
        detail = f"LLM [{provider}/{model}] failed after retries: {_unwrap_retry_error(exc)}"
    else:
        detail = f"LLM [{provider}/{model}] error: {type(exc).__name__}: {str(exc)[:300]}"
    logger.warning("llm_error_502", provider=provider, model=model, detail=detail)
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=detail)


async def ask_llm(
    prompt: str,
    system: str = "You are a helpful assistant.",
    temperature: float = 0.2,
    max_tokens: int = 512,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> str:
    p, m = _resolve(provider, model)
    provider_name = provider or llm_registry.get_active()[0]
    logger.info("llm_ask_start", provider=provider_name, model=m)
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            p.ask(prompt, system=system, model=m, temperature=temperature, max_tokens=max_tokens),
            timeout=_REQUEST_TIMEOUT_S,
        )
    except (TimeoutError, RetryError, Exception) as exc:
        raise _to_http_502(exc, provider_name, m) from exc
    logger.info("llm_ask_done", provider=provider_name, model=m, elapsed_ms=round((time.monotonic() - t0) * 1000))
    return result


async def ask_llm_json(
    prompt: str,
    system: str = "You are a helpful assistant. Always reply with valid JSON.",
    temperature: float = 0.1,
    max_tokens: int = 512,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> Any:
    p, m = _resolve(provider, model)
    provider_name = provider or llm_registry.get_active()[0]
    logger.info("llm_ask_json_start", provider=provider_name, model=m)
    t0 = time.monotonic()
    try:
        result = await asyncio.wait_for(
            p.ask_json(prompt, system=system, model=m, temperature=temperature, max_tokens=max_tokens),
            timeout=_REQUEST_TIMEOUT_S,
        )
    except (TimeoutError, RetryError, Exception) as exc:
        raise _to_http_502(exc, provider_name, m) from exc
    logger.info("llm_ask_json_done", provider=provider_name, model=m, elapsed_ms=round((time.monotonic() - t0) * 1000))
    return result
