"""Ollama provider — локально развёрнутые модели (OpenAI-совместимый API).

Особенности gemma4:31b (и других thinking-моделей в Ollama):
- По умолчанию модель уходит в «thinking mode» и оставляет message.content пустым.
- Решение: передавать "think": false прямо в JSON-теле запроса.
- Используем сырой httpx вместо openai SDK, чтобы гарантированно передать think=false.
  (openai SDK обрабатывает extra_body непредсказуемо в зависимости от версии.)
- response_format=json_object не используем — возвращает {} на thinking-моделях.
  Вместо этого: JSON-инструкция в system-промпте + extract_json из сырого текста.

Документация: https://ollama.com/blog/openai-compatibility
"""
from __future__ import annotations

import json
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.infrastructure.clients.llm_providers.base import LLMProvider
from app.infrastructure.clients.llm_providers.json_utils import extract_json
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OllamaProvider(LLMProvider):
    """
    Провайдер для локального Ollama-сервера.
    base_url — адрес с /v1, например http://10.0.21.10:11434/v1
    """

    def __init__(self, base_url: str) -> None:
        # base_url вида "http://host:port/v1" → нам нужен /v1/chat/completions
        self._chat_url = base_url.rstrip("/") + "/chat/completions"
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def ask(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant.",
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
            "think": False,  # отключить thinking mode — иначе content пустой
        }
        resp = await self._http.post(self._chat_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        finish_reason = data["choices"][0].get("finish_reason", "?")
        thinking = msg.get("thinking") or ""
        logger.info(
            "ollama_ask_done",
            model=model,
            content_len=len(content),
            thinking_len=len(thinking),
            finish_reason=finish_reason,
            content_preview=content[:150],
        )
        return content.strip()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def ask_json(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant. Always reply with valid JSON.",
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> Any:
        """
        Вызывает ask() с think=False и парсит JSON через extract_json.
        JSON-инструкция должна быть в system-промпте вызывающей стороны.
        """
        raw = await self.ask(
            prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.debug("ollama_raw", model=model, preview=raw[:300])
        try:
            return extract_json(raw)
        except ValueError as exc:
            logger.warning(
                "ollama_json_parse_failed",
                model=model,
                error=str(exc),
                raw=raw[:300],
            )
            raise
