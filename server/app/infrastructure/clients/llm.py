"""LLM client facade.

Маршрутизирует вызовы к активному провайдеру через llm_registry.
Обратная совместимость: ask_llm / ask_llm_json с теми же сигнатурами.
Per-request override: передайте provider= и/или model= для конкретного вызова.
"""
from __future__ import annotations

from typing import Any

from app.infrastructure.clients import llm_registry
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve(provider: str | None, model: str | None):
    """Вернуть (LLMProvider instance, model_name) с учётом per-request override."""
    if provider is not None:
        p = llm_registry.get_provider(provider)
        # Если модель не указана — берём первую из каталога провайдера
        if model is None:
            models = llm_registry.MODELS_CATALOG.get(provider, {}).get("models", [])
            model = models[0] if models else provider
        return p, model
    # Нет override — используем активный
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
    """Текстовый ответ LLM. provider/model — per-request override (опционально)."""
    p, m = _resolve(provider, model)
    return await p.ask(prompt, system=system, model=m, temperature=temperature, max_tokens=max_tokens)


async def ask_llm_json(
    prompt: str,
    system: str = "You are a helpful assistant. Always reply with valid JSON.",
    temperature: float = 0.1,
    max_tokens: int = 512,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> Any:
    """JSON-ответ LLM (авто-парсинг). provider/model — per-request override (опционально)."""
    p, m = _resolve(provider, model)
    return await p.ask_json(prompt, system=system, model=m, temperature=temperature, max_tokens=max_tokens)
