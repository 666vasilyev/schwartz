"""Sber GigaChat provider.

Auth: OAuth2 client_credentials (POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth).
API:  POST https://gigachat.devices.sberbank.ru/api/v1/chat/completions (OpenAI-compatible format).

Параметр auth_key — строка вида "clientId:clientSecret" или уже base64-кодированная.
Токен кэшируется и обновляется при истечении.
"""
from __future__ import annotations

import base64
import json
import time
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.infrastructure.clients.llm_providers.base import LLMProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"
_API_URL = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"
# GigaChat использует самоподписанный сертификат Сбера; для production передайте путь к CA.
_VERIFY_SSL = False


class GigaChatProvider(LLMProvider):
    """
    Провайдер GigaChat (Сбер).
    auth_key — "clientId:clientSecret" или уже base64("<clientId>:<clientSecret>").
    scope    — "GIGACHAT_API_PERS" (физ. лица) или "GIGACHAT_API_CORP" (юр. лица).
    """

    def __init__(self, auth_key: str, *, scope: str = "GIGACHAT_API_PERS", proxy: str | None = None) -> None:
        # Если не выглядит как base64 — кодируем сами
        if ":" in auth_key:
            auth_key = base64.b64encode(auth_key.encode()).decode()
        self._auth_key = auth_key
        self._scope = scope
        self._proxy = proxy
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    async def _get_token(self) -> str:
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        import uuid
        async with httpx.AsyncClient(verify=_VERIFY_SSL, proxy=self._proxy) as client:
            resp = await client.post(
                _AUTH_URL,
                headers={
                    "Authorization": f"Basic {self._auth_key}",
                    "RqUID": str(uuid.uuid4()),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                data={"scope": self._scope},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
            self._access_token = data["access_token"]
            # expires_at в миллисекундах
            self._token_expires_at = data.get("expires_at", 0) / 1000
            logger.info("gigachat_token_refreshed")
            return self._access_token  # type: ignore[return-value]

    def _build_messages(self, prompt: str, system: str) -> list[dict]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

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
        token = await self._get_token()
        async with httpx.AsyncClient(verify=_VERIFY_SSL, proxy=self._proxy) as client:
            resp = await client.post(
                _API_URL,
                headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                json={
                    "model": model,
                    "messages": self._build_messages(prompt, system),
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            if resp.status_code == 401:
                self._access_token = None  # force refresh on retry
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

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
        json_system = system + "\n\nОтвечай только валидным JSON-объектом без markdown-блоков."
        raw = await self.ask(prompt, system=json_system, model=model, temperature=temperature, max_tokens=max_tokens)
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
            raw = raw.strip()
        return json.loads(raw)
