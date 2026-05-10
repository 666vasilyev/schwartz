"""
VK API client (server-side): generic vk_call + typed helpers.
Token always comes from vk_access_tokens table (never from config).
Traceback → structlog; safe error → caller.
"""
from __future__ import annotations

from typing import Any

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.infrastructure.repositories.vk_access_token import acquire_vk_access_token
from app.utils.log_events import Events
from app.utils.logger import get_logger

logger = get_logger(__name__)

# VK API error codes worth knowing
VK_ERR_AUTH = 5          # invalid token / auth failed
VK_ERR_RATE_LIMIT = 6   # too many requests per second
VK_ERR_PERMISSION = 7   # no permission
VK_ERR_ACCESS = 15       # access denied (closed group)
VK_ERR_DELETED = 18      # user deleted or banned
VK_ERR_BLOCKED = 19      # content access denied
VK_ERR_EXPIRED = 21      # key expired
VK_ERR_WALL_LIMIT = 29  # wall.get rate limit


class VKApiError(Exception):
    def __init__(self, code: int, message: str) -> None:
        self.code = code
        super().__init__(f"VK API error {code}: {message}")


class VkNoAccessTokenConfigured(Exception):
    """No active token in vk_access_tokens table."""


class VkAccessDenied(VKApiError):
    """Group is closed / content unavailable (codes 7, 15, 19)."""


class VkRateLimit(VKApiError):
    """Too many requests (codes 6, 29)."""


class VkAuthError(VKApiError):
    """Token is invalid or expired (codes 5, 21)."""


@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=1, max=8))
async def vk_call(method: str, **params: Any) -> Any:
    settings = get_settings()
    token = await acquire_vk_access_token()
    if not token:
        raise VkNoAccessTokenConfigured("Нет активного VK-токена в таблице vk_access_tokens")

    payload = {"access_token": token, "v": settings.vk_api_version, **params}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(f"{settings.vk_api_base_url}/{method}", data=payload)
        resp.raise_for_status()

    data = resp.json()
    if "error" in data:
        err = data["error"]
        code = err.get("error_code", -1)
        msg = err.get("error_msg", "unknown")
        if code in (VK_ERR_RATE_LIMIT, VK_ERR_WALL_LIMIT):
            logger.warning(
                Events.COLLECTION_VK_RATE_LIMIT,
                message=f"VK rate limit on {method}",
                method=method,
                error_code=code,
                error_message=msg,
            )
            raise VkRateLimit(code, msg)
        if code in (VK_ERR_ACCESS, VK_ERR_PERMISSION, VK_ERR_BLOCKED):
            logger.warning(
                Events.COLLECTION_VK_FETCH_STARTED,
                message=f"VK access denied on {method}",
                method=method,
                error_code=code,
                error_message=msg,
            )
            raise VkAccessDenied(code, msg)
        if code in (VK_ERR_AUTH, VK_ERR_EXPIRED):
            logger.warning(
                Events.COLLECTION_VK_TOKEN_INVALID,
                message=f"VK token invalid on {method}",
                method=method,
                error_code=code,
                error_message=msg,
            )
            raise VkAuthError(code, msg)
        logger.warning("vk_api_error", method=method, code=code, msg=msg)
        raise VKApiError(code, msg)

    logger.debug(Events.COLLECTION_VK_FETCH_FINISHED, message=f"VK call ok: {method}", method=method)
    return data["response"]


async def vk_call_with_token(method: str, token: str, **params: Any) -> Any:
    """Call VK API with an explicit token (for token validation, not from pool)."""
    settings = get_settings()
    payload = {"access_token": token, "v": settings.vk_api_version, **params}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(f"{settings.vk_api_base_url}/{method}", data=payload)
        resp.raise_for_status()
    data = resp.json()
    if "error" in data:
        err = data["error"]
        code = err.get("error_code", -1)
        msg = err.get("error_msg", "unknown")
        raise VKApiError(code, msg)
    return data["response"]


# ── Typed helpers ──────────────────────────────────────────────────────────

_GROUP_FIELDS = (
    "description,members_count,city,country,site,status,verified,"
    "cover,photo_200,screen_name,activity,contacts,links"
)


async def resolve_screen_name(screen_name: str) -> dict[str, Any]:
    return await vk_call("utils.resolveScreenName", screen_name=screen_name)


async def get_group_info(
    group_id: int | str,
    *,
    fields: str = _GROUP_FIELDS,
) -> dict[str, Any] | None:
    """Call groups.getById, return first group dict or None."""
    resp = await vk_call("groups.getById", group_ids=str(group_id), fields=fields)
    # API returns {"groups": [...]} or just [...]
    groups = resp if isinstance(resp, list) else resp.get("groups", [resp])
    if not groups or not isinstance(groups[0], dict):
        return None
    return groups[0]


async def get_user_info(user_id: int | str = "me") -> dict[str, Any] | None:
    """users.get — used to verify token is valid."""
    resp = await vk_call("users.get", user_ids=str(user_id), fields="photo_50")
    if not isinstance(resp, list) or not resp:
        return None
    return resp[0]


async def check_token_valid(token: str) -> dict[str, Any]:
    """Validate a specific token by calling users.get with it directly."""
    try:
        resp = await vk_call_with_token("users.get", token, fields="photo_50")
        users = resp if isinstance(resp, list) else []
        if users:
            return {"valid": True, "user": users[0]}
        return {"valid": False, "reason": "empty_response"}
    except VKApiError as exc:
        return {"valid": False, "reason": str(exc), "code": exc.code}
    except Exception as exc:
        return {"valid": False, "reason": str(exc)}


async def wall_get(
    owner_id: int,
    *,
    count: int = 100,
    offset: int = 0,
    filter: str = "all",  # all | owner | others | postponed | suggests
    extended: int = 0,
) -> dict[str, Any]:
    """wall.get — returns {"count": N, "items": [...]}"""
    resp = await vk_call(
        "wall.get",
        owner_id=owner_id,
        count=min(count, 100),
        offset=offset,
        filter=filter,
        extended=extended,
    )
    if isinstance(resp, dict):
        return resp
    return {"count": 0, "items": []}


async def wall_get_comments(
    owner_id: int,
    post_id: int,
    *,
    count: int = 20,
    sort: str = "desc",
    extended: int = 1,
) -> dict[str, Any]:
    resp = await vk_call(
        "wall.getComments",
        owner_id=owner_id,
        post_id=post_id,
        count=count,
        sort=sort,
        extended=extended,
        thread_items_count=10,
    )
    return resp if isinstance(resp, dict) else {"count": 0, "items": []}
