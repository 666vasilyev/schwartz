"""DeepSeek provider — OpenAI-compatible API."""
from __future__ import annotations

from app.infrastructure.clients.llm_providers.json_utils import extract_json
from app.infrastructure.clients.llm_providers.openai_provider import OpenAIProvider
from app.utils.logger import get_logger

logger = get_logger(__name__)

_DEEPSEEK_BASE_URL = "https://api.deepseek.com"


class DeepSeekProvider(OpenAIProvider):
    """
    DeepSeek использует OpenAI-совместимый API.
    deepseek-reasoner не поддерживает response_format=json_object → парсим через extract_json.
    """

    def __init__(self, api_key: str, *, proxy: str | None = None) -> None:
        super().__init__(api_key, base_url=_DEEPSEEK_BASE_URL, proxy=proxy)

    async def ask_json(
        self,
        prompt,
        *,
        system="You are a helpful assistant. Always reply with valid JSON.",
        model,
        temperature=0.1,
        max_tokens=512,
    ):
        # deepseek-reasoner не поддерживает response_format → текстовый ask + extract_json
        if "reasoner" in model:
            raw = await self.ask(
                prompt,
                system=system + "\n\nОтвечай только валидным JSON-объектом без markdown-блоков.",
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
            )
            logger.debug("deepseek_raw_response", model=model, raw=raw[:500])
            try:
                return extract_json(raw)
            except ValueError as exc:
                logger.warning("deepseek_json_parse_failed", model=model, error=str(exc), raw=raw[:500])
                raise
        return await super().ask_json(prompt, system=system, model=model, temperature=temperature, max_tokens=max_tokens)
