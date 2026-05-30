"""Get and refresh VK group metadata for a source."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.source import get_source_by_id, update_source
from app.infrastructure.vk.client import VKApiError, get_group_info
from app.presentation.schemas.vk import VkGroupMetadata, VkMetadataRefreshResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

_COVER_FIELDS = ("description", "members_count", "site", "status", "verified", "cover", "photo_200", "screen_name", "activity")


def _extract_cover_url(group: dict) -> str | None:
    cover = group.get("cover")
    if isinstance(cover, dict) and cover.get("enabled"):
        images = cover.get("images") or []
        if images:
            return images[-1].get("url")
    return None


def _build_metadata(group: dict) -> VkGroupMetadata:
    gid = group.get("id") or 0
    return VkGroupMetadata(
        owner_id=-abs(int(gid)),
        name=group.get("name"),
        screen_name=group.get("screen_name"),
        description=group.get("description"),
        members_count=group.get("members_count"),
        verified=bool(group.get("verified")),
        site=group.get("site"),
        activity=group.get("activity"),
        photo_url=group.get("photo_200"),
        cover_url=_extract_cover_url(group),
        fetched_at=datetime.now(tz=timezone.utc),
    )


async def get_metadata(db: AsyncSession, source_id: int) -> VkGroupMetadata:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if src.source_type != "vk":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Источник не является VK-группой")

    meta = src.source_metadata or {}
    gid = src.vk_owner_id
    if not gid:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="owner_id не заполнен для источника")

    return VkGroupMetadata(
        owner_id=int(gid),
        name=src.name or meta.get("name"),
        screen_name=src.username or meta.get("screen_name"),
        description=src.description or meta.get("description"),
        members_count=meta.get("members_count"),
        verified=meta.get("verified"),
        site=meta.get("site"),
        activity=meta.get("activity"),
        photo_url=meta.get("photo_url"),
        cover_url=meta.get("cover_url"),
        fetched_at=meta.get("fetched_at"),
    )


async def refresh_metadata(db: AsyncSession, source_id: int) -> VkMetadataRefreshResponse:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if src.source_type != "vk":
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Источник не является VK-группой")

    owner_id = src.vk_owner_id
    if not owner_id:
        return VkMetadataRefreshResponse(source_id=source_id, refreshed=False, error="owner_id не заполнен")

    try:
        group = await get_group_info(owner_id)
    except VKApiError as exc:
        return VkMetadataRefreshResponse(source_id=source_id, refreshed=False, error=str(exc))
    except Exception as exc:
        logger.warning("vk_metadata_refresh_error", source_id=source_id, error=str(exc))
        return VkMetadataRefreshResponse(source_id=source_id, refreshed=False, error=str(exc))

    if group is None:
        return VkMetadataRefreshResponse(source_id=source_id, refreshed=False, error="Группа не найдена")

    built = _build_metadata(group)
    new_meta = dict(src.source_metadata or {})
    new_meta.update({
        "name": built.name,
        "screen_name": built.screen_name,
        "description": built.description,
        "members_count": built.members_count,
        "verified": built.verified,
        "site": built.site,
        "activity": built.activity,
        "photo_url": built.photo_url,
        "cover_url": built.cover_url,
        "fetched_at": built.fetched_at.isoformat() if built.fetched_at else None,
    })

    await update_source(
        db,
        source_id,
        source_metadata=new_meta,
        name=built.name or src.name,
        description=built.description or src.description,
    )

    return VkMetadataRefreshResponse(source_id=source_id, refreshed=True, metadata=built)
