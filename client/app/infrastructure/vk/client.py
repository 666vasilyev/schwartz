from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.infrastructure.repositories.vk_access_token import acquire_vk_access_token
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_VK_BASE = settings.vk_api_base_url
_VERSION = settings.vk_api_version


class VKApiError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"VK API error {code}: {message}")


class VkNoAccessTokenConfigured(Exception):
    pass


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def vk_call(method: str, **params: Any) -> dict[str, Any]:
    token = await acquire_vk_access_token()
    if not token:
        raise VkNoAccessTokenConfigured("Нет активного VK токена")

    payload = {
        "access_token": token,
        "v": _VERSION,
        **params,
    }
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{_VK_BASE}/{method}", data=payload)
        resp.raise_for_status()

    data = resp.json()

    if "error" in data:
        err = data["error"]
        raise VKApiError(err.get("error_code", -1), err.get("error_msg", "unknown"))

    logger.debug("vk_call_ok", method=method)
    return data["response"]


async def resolve_screen_name(screen_name: str) -> dict:
    return await vk_call("utils.resolveScreenName", screen_name=screen_name)


async def wall_get(owner_id: int, count: int = 20) -> dict:
    return await vk_call("wall.get", owner_id=owner_id, count=count)


async def wall_get_comments(
    owner_id: int,
    post_id: int,
    *,
    count: int = 20,
    sort: str = "desc",
    extended: int = 1,
) -> dict:
    return await vk_call(
        "wall.getComments",
        owner_id=owner_id,
        post_id=post_id,
        count=count,
        sort=sort,
        extended=extended,
    )
