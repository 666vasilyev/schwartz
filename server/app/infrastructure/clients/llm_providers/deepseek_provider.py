"""DeepSeek provider — OpenAI-compatible API."""
from __future__ import annotations

from app.infrastructure.clients.llm_providers.openai_provider import OpenAIProvider

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(OpenAIProvider):
    """
    DeepSeek использует OpenAI-совместимый API.
    Переопределяем только base_url и не передаём response_format (DeepSeek его поддерживает,
    но некоторые модели типа deepseek-reasoner — нет; см. ask_json ниже).
    """

    def __init__(self, api_key: str, *, proxy: str | None = None) -> None:
        super().__init__(api_key, base_url=_DEEPSEEK_BASE_URL, proxy=proxy)

    async def ask_json(self, prompt, *, system="You are a helpful assistant. Always reply with valid JSON.", model, temperature=0.1, max_tokens=512):
        import json
        from tenacity import retry, stop_after_attempt, wait_exponential

        # deepseek-reasoner не поддерживает response_format → используем обычный ask + parse
        if "reasoner" in model:
            raw = await self.ask(prompt, system=system + "\n\nОтвечай только валидным JSON без markdown.", model=model, temperature=temperature, max_tokens=max_tokens)
            # Strip possible markdown code block
            raw = raw.strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            return json.loads(raw.strip())
        return await super().ask_json(prompt, system=system, model=model, temperature=temperature, max_tokens=max_tokens)
