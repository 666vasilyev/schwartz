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
    "openai": {
        "label": "OpenAI",
        "models": [
            "gpt-4o",
            "gpt-4o-mini",
            "gpt-4.1",
            "gpt-4.1-mini",
            "gpt-4-turbo",
            "gpt-3.5-turbo",
            "o3",
            "o4-mini",
        ],
    },
    "deepseek": {
        "label": "DeepSeek",
        "models": [
            "deepseek-chat",
            "deepseek-reasoner",
        ],
    },
    "gigachat": {
        "label": "GigaChat (Сбер)",
        "models": [
            "GigaChat",
            "GigaChat-Pro",
            "GigaChat-Max",
            "GigaChat-2",
            "GigaChat-2-Pro",
            "GigaChat-2-Max",
        ],
    },
    "yandexgpt": {
        "label": "YandexGPT",
        "models": [
            "yandexgpt-lite",
            "yandexgpt",
            "yandexgpt-32k",
        ],
    },
}

# ── Активный провайдер / модель (runtime state) ──────────────────────────────

_active_provider_name: str | None = None
_active_model: str | None = None

# Кэш инстансов провайдеров (создаём лениво)
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
    from app.infrastructure.clients.llm_providers.deepseek_provider import DeepSeekProvider
    from app.infrastructure.clients.llm_providers.gigachat_provider import GigaChatProvider
    from app.infrastructure.clients.llm_providers.openai_provider import OpenAIProvider
    from app.infrastructure.clients.llm_providers.yandexgpt_provider import YandexGPTProvider

    if provider_name is None:
        provider_name, _ = get_active()

    if provider_name in _provider_instances:
        return _provider_instances[provider_name]

    s = get_settings()
    proxy = s.proxy or None

    if provider_name == "openai":
        instance = OpenAIProvider(
            api_key=s.openai_api_key,
            proxy=proxy,
            raise_on_proxy_unavailable=bool(proxy),  # только если прокси задан
        )
    elif provider_name == "deepseek":
        instance = DeepSeekProvider(api_key=s.deepseek_api_key, proxy=proxy)
    elif provider_name == "gigachat":
        instance = GigaChatProvider(
            auth_key=s.gigachat_auth_key,
            scope=s.gigachat_scope,
            proxy=None,  # Sber — российский сервис, прокси не нужен
            use_new_api_url=s.gigachat_use_new_api_url,
        )
    elif provider_name == "yandexgpt":
        instance = YandexGPTProvider(api_key=s.yandex_api_key, folder_id=s.yandex_folder_id, proxy=None)  # российский сервис
    else:
        raise ValueError(f"Неизвестный провайдер: {provider_name!r}")

    _provider_instances[provider_name] = instance
    return instance


def get_active_provider():
    """Сокращение: активный провайдер + текущая модель."""
    provider_name, model = get_active()
    return get_provider(provider_name), model
