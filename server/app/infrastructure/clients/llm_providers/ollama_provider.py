"""Ollama provider — локально развёрнутые модели (OpenAI-совместимый API).

Ollama поднимает OpenAI-совместимый сервер на /v1/chat/completions.
API-ключ не нужен — передаём dummy "ollama".
Прокси не нужен — сервер в локальной сети.

Документация: https://ollama.com/blog/openai-compatibility
"""
from __future__ import annotations

from typing import Any

from app.infrastructure.clients.llm_providers.json_utils import extract_json
from app.infrastructure.clients.llm_providers.openai_provider import OpenAIProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaProvider(OpenAIProvider):
    """
    Провайдер для локального Ollama-сервера.

    base_url — адрес Ollama, например http://10.0.21.10:11434/v1
    Ollama поддерживает OpenAI-совместимый API, но response_format=json_object
    доступен не на всех моделях → используем extract_json() на текстовом ответе.
    """

    def __init__(self, base_url: str) -> None:
        super().__init__(
            api_key="ollama",      # dummy — Ollama не требует ключа
            base_url=base_url,
            proxy=None,            # локальная сеть, прокси не нужен
            raise_on_proxy_unavailable=False,
        )
        self._base_url = base_url

    async def ask_json(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant. Always reply with valid JSON.",
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> Any:
        # Ollama не всегда поддерживает response_format → plain text + extract_json
        raw = await self.ask(
            prompt,
            system=system + "\n\nОтвечай только валидным JSON-объектом без markdown-блоков.",
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.debug("ollama_raw_response", model=model, raw=raw[:500])
        try:
            return extract_json(raw)
        except ValueError as exc:
            logger.warning("ollama_json_parse_failed", model=model, error=str(exc), raw=raw[:500])
            raise
