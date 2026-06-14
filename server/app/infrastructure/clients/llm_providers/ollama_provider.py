"""Ollama provider — локально развёрнутые модели (OpenAI-совместимый API).

Особенности gemma4:31b (и других thinking-моделей в Ollama):
- По умолчанию модель уходит в «thinking mode» и оставляет message.content пустым.
- Решение: передавать extra_body={"think": False} — отключает thinking mode,
  модель сразу пишет ответ в content.
- response_format=json_object с thinking-моделью возвращает пустой {} → не используем.
  Вместо этого просим JSON в системном промпте и парсим через extract_json.

Документация: https://ollama.com/blog/openai-compatibility
"""
from __future__ import annotations

from typing import Any

from app.infrastructure.clients.llm_providers.json_utils import extract_json
from app.infrastructure.clients.llm_providers.openai_provider import OpenAIProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)

# Передаётся в каждый запрос к Ollama чтобы отключить thinking mode
_OLLAMA_EXTRA_BODY = {"think": False}


class OllamaProvider(OpenAIProvider):
    """
    Провайдер для локального Ollama-сервера.

    base_url — адрес Ollama, например http://10.0.21.10:11434/v1
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(
            api_key="ollama",      # dummy — Ollama не требует ключа
            base_url=base_url,
            proxy=None,            # локальная сеть, прокси не нужен
            raise_on_proxy_unavailable=False,
        )

    async def ask(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant.",
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
        extra_body: dict | None = None,
    ) -> str:
        """Передаём think=False чтобы модель писала ответ в content, а не в thinking."""
        body = {**_OLLAMA_EXTRA_BODY, **(extra_body or {})}
        return await super().ask(
            prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=body,
        )

    async def ask_json(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant. Always reply with valid JSON.",
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
        extra_body: dict | None = None,
    ) -> Any:
        """
        Не используем response_format=json_object (возвращает пустой {} на thinking-модели).
        Вместо этого: ask() с think=False + extract_json из сырого текста.
        JSON-инструкция должна быть в system-промпте (см. schwartz_values.py, text.py).
        """
        raw = await self.ask(
            prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            extra_body=extra_body,
        )
        logger.debug("ollama_raw", model=model, preview=raw[:300])
        try:
            return extract_json(raw)
        except ValueError as exc:
            logger.warning("ollama_json_parse_failed", model=model, error=str(exc), raw=raw[:300])
            raise
