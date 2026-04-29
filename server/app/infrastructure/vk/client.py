"""
Минимальный вызов VK API на сервере (только resolveScreenName для регистрации источника).
Токен опционален: без токена owner_id не резолвится до первого сбора на клиенте.
"""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)


class VKApiError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"VK API error {code}: {message}")


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def vk_call(method: str, **params: Any) -> dict[str, Any]:
    settings = get_settings()
    payload = {
        "access_token": settings.vk_api_token,
        "v": settings.vk_api_version,
        **params,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{settings.vk_api_base_url}/{method}", data=payload)
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        err = data["error"]
        raise VKApiError(err.get("error_code", -1), err.get("error_msg", "unknown"))

    logger.debug("vk_call_ok", method=method)
    return data["response"]


async def resolve_screen_name(screen_name: str) -> dict[str, Any]:
    return await vk_call("utils.resolveScreenName", screen_name=screen_name)
