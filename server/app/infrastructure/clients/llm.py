"""LLM client facade.

Маршрутизирует вызовы к активному провайдеру через llm_registry.
Per-request override: передайте provider= и/или model= для конкретного вызова.
"""
from __future__ import annotations

import time
from typing import Any

from fastapi import HTTPException, status

from app.infrastructure.clients import llm_registry
from app.infrastructure.clients.llm_providers.openai_provider import ProxyUnavailableError
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve(provider: str | None, model: str | None):
    if provider is not None:
        p = llm_registry.get_provider(provider)
        if model is None:
            models = llm_registry.MODELS_CATALOG.get(provider, {}).get("models", [])
            model = models[0] if models else provider
        return p, model
    return llm_registry.get_active_provider()


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
        result = await p.ask(prompt, system=system, model=m, temperature=temperature, max_tokens=max_tokens)
    except ProxyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Proxy unavailable: {exc.proxy}",
        ) from exc
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
        result = await p.ask_json(prompt, system=system, model=m, temperature=temperature, max_tokens=max_tokens)
    except ProxyUnavailableError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Proxy unavailable: {exc.proxy}",
        ) from exc
    logger.info("llm_ask_json_done", provider=provider_name, model=m, elapsed_ms=round((time.monotonic() - t0) * 1000))
    return result
