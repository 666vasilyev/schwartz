"""YandexGPT provider.

Auth:  Authorization: Api-Key <api_key>
       x-folder-id: <folder_id>
API:   POST https://llm.api.cloud.yandex.net/foundationModels/v1/completion
Model: gpt://<folder_id>/<model_name>/latest

Формат запроса отличается от OpenAI: поля modelUri, completionOptions, messages[].text.
Документация: https://yandex.cloud/en/docs/foundation-models/quickstart/yandexgpt
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

_API_URL = "https://llm.api.cloud.yandex.net/foundationModels/v1/completion"


class YandexGPTProvider(LLMProvider):
    """
    Провайдер YandexGPT (Яндекс.Облако).
    api_key   — API-ключ сервисного аккаунта (IAM-токен не поддерживаем — он краткоживущий).
    folder_id — идентификатор каталога Яндекс.Облако (b1g...).
    """

    def __init__(self, api_key: str, folder_id: str, *, proxy: str | None = None) -> None:
        self._api_key = api_key
        self._folder_id = folder_id
        self._proxy = proxy

    def _model_uri(self, model: str) -> str:
        """Собрать полный modelUri. Если уже gpt://... — оставить как есть."""
        if model.startswith("gpt://"):
            return model
        return f"gpt://{self._folder_id}/{model}/latest"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Api-Key {self._api_key}",
            "x-folder-id": self._folder_id,   # рекомендован документацией
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    def _build_body(
        self,
        prompt: str,
        system: str,
        model: str,
        temperature: float,
        max_tokens: int,
    ) -> dict:
        return {
            "modelUri": self._model_uri(model),
            "completionOptions": {
                "stream": False,
                "temperature": temperature,
                "maxTokens": str(max_tokens),  # API ожидает строку
            },
            "messages": [
                {"role": "system", "text": system},
                {"role": "user", "text": prompt},
            ],
        }

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
        async with httpx.AsyncClient(proxy=self._proxy) as client:
            resp = await client.post(
                _API_URL,
                headers=self._headers(),
                json=self._build_body(prompt, system, model, temperature, max_tokens),
                timeout=60,
            )
            resp.raise_for_status()
            data = resp.json()
            text = data["result"]["alternatives"][0]["message"]["text"]
            logger.debug("yandexgpt_ask", model=model, usage=data.get("result", {}).get("usage"))
            return text.strip()

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
        raw = await self.ask(
            prompt,
            system=json_system,
            model=model,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        logger.debug("yandexgpt_raw_response", raw=raw[:500])
        try:
            return extract_json(raw)
        except ValueError as exc:
            logger.warning("yandexgpt_json_parse_failed", error=str(exc), raw=raw[:500])
            raise
