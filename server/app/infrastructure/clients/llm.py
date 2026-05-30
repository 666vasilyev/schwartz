from typing import Any
import httpx
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential
from app.core.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_http_client = httpx.AsyncClient(proxy=settings.proxy) if settings.proxy else None
_client = AsyncOpenAI(api_key=settings.openai_api_key, http_client=_http_client)


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def ask_llm(
    prompt: str,
    system: str = "You are a helpful assistant.",
    temperature: float = 0.2,
    max_tokens: int = 512,
) -> str:
    """Send a single-turn prompt and return the text reply."""
    response = await _client.chat.completions.create(
        model=settings.openai_model,
        temperature=temperature,
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": prompt},
        ],
    )
    reply = response.choices[0].message.content or ""
    logger.debug("llm_reply", tokens=response.usage.total_tokens if response.usage else None)
    return reply.strip()


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
async def ask_llm_json(
    prompt: str,
    system: str = "You are a helpful assistant. Always reply with valid JSON.",
    temperature: float = 0.1,
    max_tokens: int = 512,
) -> Any:
    """Like ask_llm but enforces JSON response format and auto-parses."""
    import json

    response = await _client.chat.completions.create(
        model=settings.openai_model,
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
