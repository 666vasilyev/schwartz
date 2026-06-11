"""Sber GigaChat provider.

Auth:  POST https://ngw.devices.sberbank.ru:9443/api/v2/oauth  (OAuth2 client_credentials)
       Заголовок Authorization: Basic base64(clientId:clientSecret)
       Заголовок RqUID: uuid4  (обязателен по документации)
       Тело: scope=GIGACHAT_API_PERS | GIGACHAT_API_B2B | GIGACHAT_API_CORP

API:   https://api.giga.chat/v1/chat/completions  (новый URL, нормальный SSL, OpenAI-совместимый)
       Fallback: https://gigachat.devices.sberbank.ru/api/v1/chat/completions (старый, verify=False)

Параметр auth_key — строка вида "clientId:clientSecret" или уже base64-кодированная.
Токен кэшируется 30 минут, обновляется при истечении или 401.

Документация: https://developers.sber.ru/docs/ru/gigachat/api/reference/rest/gigachat-api
"""
from __future__ import annotations

import base64
import json
import time
import uuid
from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.infrastructure.clients.llm_providers.base import LLMProvider
from app.infrastructure.clients.llm_providers.json_utils import extract_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

_AUTH_URL = "https://ngw.devices.sberbank.ru:9443/api/v2/oauth"

# Новый URL — валидный SSL-сертификат, предпочтительный
_API_URL_NEW = "https://api.giga.chat/v1/chat/completions"
# Старый URL — самоподписанный сертификат Сбера
_API_URL_OLD = "https://gigachat.devices.sberbank.ru/api/v1/chat/completions"


class GigaChatProvider(LLMProvider):
    """
    Провайдер GigaChat (Сбер).

    auth_key — "clientId:clientSecret" или уже base64-строка.
    scope    — "GIGACHAT_API_PERS" (физ. лица, default)
               "GIGACHAT_API_B2B"  (ИП/юр. лица, платный пакет)
               "GIGACHAT_API_CORP" (ИП/юр. лица, pay-as-you-go)
    use_new_api_url — True (default): api.giga.chat с нормальным SSL
                      False: gigachat.devices.sberbank.ru (требует verify=False)
    """

    def __init__(
        self,
        auth_key: str,
        *,
        scope: str = "GIGACHAT_API_PERS",
        proxy: str | None = None,
        use_new_api_url: bool = True,
    ) -> None:
        # Если передан "clientId:clientSecret" — кодируем в base64
        if ":" in auth_key:
            auth_key = base64.b64encode(auth_key.encode()).decode()
        self._auth_key = auth_key
        self._scope = scope
        self._proxy = proxy
        self._api_url = _API_URL_NEW if use_new_api_url else _API_URL_OLD
        self._verify_ssl = False  # Sber использует нестандартные сертификаты на всех эндпоинтах
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ── Получение и кэширование токена ──────────────────────────────────────

    async def _get_token(self) -> str:
        """Вернуть токен. Обновить если истёк (с запасом 30 сек)."""
        if self._access_token and time.time() < self._token_expires_at - 30:
            return self._access_token

        # Токен запрашивается к старому ngw-эндпоинту — там самоподписанный сертификат
        async with httpx.AsyncClient(verify=False, proxy=self._proxy) as client:
            resp = await client.post(
                _AUTH_URL,
                headers={
                    "Authorization": f"Basic {self._auth_key}",
                    "RqUID": str(uuid.uuid4()),  # обязательный заголовок по API
                    "Content-Type": "application/x-www-form-urlencoded",
                    "Accept": "application/json",
                },
                data={"scope": self._scope},
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()

        self._access_token = data["access_token"]
        # expires_at приходит в миллисекундах
        self._token_expires_at = data.get("expires_at", 0) / 1000
        logger.info("gigachat_token_refreshed", expires_at=self._token_expires_at)
        return self._access_token  # type: ignore[return-value]

    # ── Вспомогательные методы ───────────────────────────────────────────────

    def _build_messages(self, prompt: str, system: str) -> list[dict]:
        return [
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ]

    def _http_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(verify=self._verify_ssl, proxy=self._proxy)

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
        token = await self._get_token()
        async with self._http_client() as client:
            resp = await client.post(
                self._api_url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json={
                    "model": model,
                    "messages": self._build_messages(prompt, system),
                    "temperature": temperature,
                    "max_tokens": max_tokens,
                },
                timeout=60,
            )
            if resp.status_code == 401:
                # Токен протух — сбрасываем, tenacity сделает повтор
                self._access_token = None
                resp.raise_for_status()
            resp.raise_for_status()
            return resp.json()["choices"][0]["message"]["content"].strip()

    async def ask_json(
        self,
        prompt: str,
        *,
        system: str = "You are a helpful assistant. Always reply with valid JSON.",
        model: str,
        temperature: float = 0.1,
        max_tokens: int = 512,
    ) -> Any:
        # Нет @retry здесь — self.ask() уже имеет @retry(3), двойной ретрай даёт RetryError[RetryError]
        json_system = system + "\n\nОтвечай только валидным JSON-объектом без markdown-блоков."
        raw = await self.ask(
            prompt,
            system=json_system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.debug("gigachat_raw_response", raw=raw[:500])
        try:
            return extract_json(raw)
        except ValueError as exc:
            logger.warning("gigachat_json_parse_failed", error=str(exc), raw=raw[:500])
            raise
