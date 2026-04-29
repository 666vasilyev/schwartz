from __future__ import annotations

import httpx

from app.infrastructure.repositories.vk_access_token import vk_token_sources_configured_async
from app.infrastructure.vk.client import (
    VKApiError,
    VkNoAccessTokenConfigured,
    resolve_screen_name,
)
from app.infrastructure.vk.vk_public_url import extract_screen_or_id_token
from app.utils.logger import get_logger

logger = get_logger(__name__)


def owner_id_from_resolve(resp: dict) -> int:
    t = (resp.get("type") or "").lower()
    oid = int(resp.get("object_id", 0))
    if t in ("group", "page", "event"):
        return -oid
    if t == "user":
        return oid
    raise ValueError(
        f"utils.resolveScreenName: неподдерживаемый type={t!r} (нужен user/group/page/event)"
    )


async def resolve_vk_owner_id(segment: str) -> int | None:
    _token, precomputed = extract_screen_or_id_token(segment)
    if precomputed is not None:
        return precomputed
    if not await vk_token_sources_configured_async():
        return None
    try:
        res = await resolve_screen_name(_token)
    except VkNoAccessTokenConfigured:
        return None
    except (VKApiError, OSError, httpx.HTTPError) as exc:
        logger.warning("vk_resolve_failed", segment=segment, error=str(exc))
        return None
    if not res:
        return None
    try:
        return owner_id_from_resolve(res)
    except ValueError as exc:
        logger.warning("vk_resolve_bad_type", segment=segment, error=str(exc))
        return None
