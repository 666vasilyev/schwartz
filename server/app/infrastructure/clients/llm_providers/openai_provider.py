"""OpenAI provider (also works for any OpenAI-compatible endpoint)."""
from __future__ import annotations

import json
from typing import Any

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.infrastructure.clients.llm_providers.base import LLMProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)


class OpenAIProvider(LLMProvider):
    """
    Провайдер OpenAI.
    Принимает base_url для совместимых API (например, DeepSeek).
    """

    def __init__(self, api_key: str, *, base_url: str | None = None, proxy: str | None = None) -> None:
        http_client = httpx.AsyncClient(proxy=proxy) if proxy else None
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
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
        response = await self._client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        reply = response.choices[0].message.content or ""
        logger.debug("openai_ask", model=model, tokens=response.usage.total_tokens if response.usage else None)
        return reply.strip()

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
        response = await self._client.chat.completions.create(
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": prompt},
            ],
        )
        raw = response.choices[0].message.content or "{}"
        return json.loads(raw)
