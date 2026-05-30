"""Resolve a VK URL or screen_name to group/user metadata."""
from __future__ import annotations

from app.infrastructure.vk.client import VKApiError, get_group_info, resolve_screen_name
from app.infrastructure.vk.vk_public_url import (
    extract_screen_or_id_token,
    public_path_segment_from_url,
)
from app.presentation.schemas.vk import VkResolveRequest, VkResolvedSource
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _determine_source_type(group: dict) -> str:
    return "vk"


def _cover_url(group: dict) -> str | None:
    cover = group.get("cover")
    if isinstance(cover, dict) and cover.get("enabled"):
        images = cover.get("images") or []
        if images:
            return images[-1].get("url")
    return None


async def execute(body: VkResolveRequest) -> VkResolvedSource:
    raw = body.url.strip()
    if raw.startswith("http") or "vk.com" in raw or "vk.ru" in raw:
        segment = public_path_segment_from_url(raw)
    else:
        segment = raw

    screen_name, numeric_id = extract_screen_or_id_token(segment)

    if numeric_id is not None:
        group = await get_group_info(numeric_id)
    else:
        resolved = await resolve_screen_name(screen_name)
        obj_type = resolved.get("type", "")
        obj_id = resolved.get("object_id")
        if obj_type not in ("group", "page", "public") or obj_id is None:
            raise ValueError(f"'{screen_name}' не является группой VK")
        group = await get_group_info(obj_id)

    if group is None:
        raise ValueError("Группа не найдена или недоступна")

    gid = group.get("id") or 0
    owner_id = -abs(int(gid))

    return VkResolvedSource(
        screen_name=group.get("screen_name") or segment,
        owner_id=owner_id,
        source_type=_determine_source_type(group),
        name=group.get("name"),
        members_count=group.get("members_count"),
        description=group.get("description"),
        site=group.get("site"),
        verified=bool(group.get("verified")),
        photo_url=group.get("photo_200") or _cover_url(group),
    )
