"""OpenAI provider (also works for any OpenAI-compatible endpoint)."""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any
from urllib.parse import urlparse

import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.infrastructure.clients.llm_providers.base import LLMProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PROXY_CHECK_TTL = 30.0    # секунд между повторными проверками
_PROXY_CHECK_TIMEOUT = 3.0  # таймаут TCP-соединения к прокси


class ProxyUnavailableError(RuntimeError):
    """Прокси недоступен — запрос к LLM отменён."""
    def __init__(self, proxy: str) -> None:
        super().__init__(f"Proxy unavailable: {proxy}")
        self.proxy = proxy


async def _tcp_check(host: str, port: int) -> bool:
    """Проверить TCP-доступность host:port."""
    try:
        _, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=_PROXY_CHECK_TIMEOUT,
        )
        writer.close()
        await writer.wait_closed()
        return True
    except Exception:
        return False


class OpenAIProvider(LLMProvider):
    """
    Провайдер OpenAI.
    Принимает base_url для совместимых API (например, DeepSeek).
    Если задан proxy — проверяет TCP-доступность перед каждым вызовом
    (результат кэшируется на _PROXY_CHECK_TTL секунд).
    """

    def __init__(
        self,
        api_key: str,
        *,
        base_url: str | None = None,
        proxy: str | None = None,
        raise_on_proxy_unavailable: bool = False,
    ) -> None:
        self._proxy = proxy
        self._raise_on_proxy_unavailable = raise_on_proxy_unavailable
        http_client = (
            httpx.AsyncClient(proxy=proxy, timeout=httpx.Timeout(120.0, connect=15.0))
            if proxy else None
        )
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            http_client=http_client,
        )
        # Кэш результата проверки прокси
        self._proxy_ok: bool | None = None
        self._proxy_checked_at: float = 0.0

    # ── Проверка прокси ──────────────────────────────────────────────────────

    async def _check_proxy(self) -> None:
        """
        Если proxy задан — проверить TCP-доступность.
        Результат кэшируется на _PROXY_CHECK_TTL секунд.
        При недоступности логирует WARNING, но не бросает исключение
        (запрос всё равно отправляется — возможно прокси поднимется).
        """
        if not self._proxy:
            return
        now = time.monotonic()
        if self._proxy_ok is not None and now - self._proxy_checked_at < _PROXY_CHECK_TTL:
            if not self._proxy_ok:
                logger.warning("proxy_unavailable_cached", proxy=self._proxy)
                if self._raise_on_proxy_unavailable:
                    raise ProxyUnavailableError(self._proxy)
            return

        parsed = urlparse(self._proxy)
        host = parsed.hostname or ""
        port = parsed.port or (1080 if (parsed.scheme or "").startswith("socks") else 8080)

        ok = await _tcp_check(host, port)
        self._proxy_ok = ok
        self._proxy_checked_at = now

        if ok:
            logger.info("proxy_ok", proxy=self._proxy, host=host, port=port)
        else:
            logger.warning(
                "proxy_unavailable",
                proxy=self._proxy,
                host=host,
                port=port,
                raise_=self._raise_on_proxy_unavailable,
            )
            if self._raise_on_proxy_unavailable:
                raise ProxyUnavailableError(self._proxy)

    # ── API-вызовы ───────────────────────────────────────────────────────────

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
        await self._check_proxy()
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
        await self._check_proxy()
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
