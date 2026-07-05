"""LLM provider registry.

Каталог моделей по провайдерам; активный провайдер и модель.
Инициализируется из настроек, можно переключить в рантайме через API.
"""
from __future__ import annotations

from typing import Any

from app.utils.logger import get_logger

logger = get_logger(__name__)

# ── Каталог моделей ──────────────────────────────────────────────────────────

MODELS_CATALOG: dict[str, dict[str, Any]] = {
    "ollama": {
        "label": "Ollama (локальный сервер)",
        "models": [
            "gemma4:31b",
        ],
    },
    "openai": {
        "label": "OpenAI (облако)",
        "models": [
            "gpt-5.5",
            "gpt-5.5-pro",
            "gpt-5.4",
            "gpt-5.4-mini",
            "gpt-5.4-nano",
        ],
    },
}

# ── Активный провайдер / модель (runtime state) ──────────────────────────────

_active_provider_name: str | None = None
_active_model: str | None = None

# Кэш инстансов провайдеров (создаётся лениво)
_provider_instances: dict[str, Any] = {}


def init_from_settings() -> None:
    """Вызывается при старте приложения — читает настройки и задаёт defaults."""
    global _active_provider_name, _active_model
    from app.core.config import get_settings

    s = get_settings()
    _active_provider_name = s.llm_provider
    _active_model = s.llm_model
    logger.info("llm_registry_init", provider=_active_provider_name, model=_active_model)


def get_active() -> tuple[str, str]:
    """Вернуть (provider_name, model)."""
    if _active_provider_name is None:
        init_from_settings()
    return _active_provider_name, _active_model  # type: ignore[return-value]


def set_active(provider_name: str, model: str) -> None:
    """Переключить активный провайдер и модель в рантайме."""
    global _active_provider_name, _active_model
    if provider_name not in MODELS_CATALOG:
        raise ValueError(f"Неизвестный провайдер: {provider_name!r}. Доступны: {list(MODELS_CATALOG)}")
    _active_provider_name = provider_name
    _active_model = model
    logger.info("llm_active_changed", provider=provider_name, model=model)


def get_provider(provider_name: str | None = None):
    """Вернуть инстанс провайдера (создаётся лениво, кэшируется)."""
    from app.core.config import get_settings
    from app.infrastructure.clients.llm_providers.ollama_provider import OllamaProvider
    from app.infrastructure.clients.llm_providers.openai_provider import OpenAIProvider

    if provider_name is None:
        provider_name, _ = get_active()

    if provider_name in _provider_instances:
        return _provider_instances[provider_name]

    s = get_settings()

    if provider_name == "ollama":
        instance = OllamaProvider(base_url=s.ollama_base_url)
    elif provider_name == "openai":
        instance = OpenAIProvider(api_key=s.openai_api_key, base_url=s.openai_base_url, proxy=s.proxy or None)
    else:
        raise ValueError(f"Неизвестный провайдер: {provider_name!r}. Доступны: {list(MODELS_CATALOG)}")

    _provider_instances[provider_name] = instance
    return instance


def get_active_provider():
    """Сокращение: активный провайдер + текущая модель."""
    provider_name, model = get_active()
    return get_provider(provider_name), model
