"""OpenAI provider — облачный API (Chat Completions).

В отличие от OllamaProvider, здесь можно полагаться на честный
response_format={"type": "json_object"} — реальный OpenAI его соблюдает
надёжно (в отличие от локальных thinking-моделей). extract_json оставлен как
подстраховка на случай, если модель всё же обернёт JSON в лишний текст.

Прокси: тот же settings.proxy, что используется для Telegram (см.
app/infrastructure/telegram/client.py) — IP датацентра часто блокируется
OpenAI (403 Forbidden), поэтому трафик заворачивается через тот же SOCKS5.
httpx (с установленным httpx[socks]) принимает прокси прямо URL-строкой,
без ручной конвертации в кортеж, как это нужно для Telethon.
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


class OpenAIProvider(LLMProvider):
    """
    Провайдер для OpenAI API.
    base_url — адрес с /v1, например https://api.openai.com/v1
    proxy — тот же SOCKS5, что и для Telegram, например socks5://host-gateway:1080
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.openai.com/v1",
        proxy: str | None = None,
    ) -> None:
        if not api_key:
            logger.warning("openai_provider_no_api_key")
        self._chat_url = base_url.rstrip("/") + "/chat/completions"
        logger.info("openai_provider_init", proxy_configured=bool(proxy))
        self._http = httpx.AsyncClient(
            timeout=httpx.Timeout(120.0, connect=10.0),
            headers={"Authorization": f"Bearer {api_key}"},
            proxy=proxy or None,
        )

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _complete(
        self,
        prompt: str,
        *,
        system: str,
        model: str,
        temperature: float,
        max_tokens: int,
        response_format: dict | None = None,
    ) -> str:
        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
            "stream": False,
        }
        if response_format is not None:
            payload["response_format"] = response_format

        resp = await self._http.post(self._chat_url, json=payload)
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content") or ""
        finish_reason = data["choices"][0].get("finish_reason", "?")
        usage = data.get("usage", {})
        logger.info(
            "openai_ask_done",
            model=model,
            content_len=len(content),
            finish_reason=finish_reason,
            prompt_tokens=usage.get("prompt_tokens"),
            completion_tokens=usage.get("completion_tokens"),
            content_preview=content[:150],
        )
        return content.strip()

    async def ask(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant.",
        model: str,
        temperature: float = 0.2,
        max_tokens: int = 512,
    ) -> str:
        return await self._complete(
            prompt, system=system, model=model, temperature=temperature, max_tokens=max_tokens
        )

    async def ask_json(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant. Always reply with valid JSON.",
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> Any:
        raw = await self._complete(
            prompt,
            system=system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
        )
        try:
            return extract_json(raw)
        except ValueError as exc:
            logger.warning("openai_json_parse_failed", model=model, error=str(exc), raw=raw[:300])
            raise
