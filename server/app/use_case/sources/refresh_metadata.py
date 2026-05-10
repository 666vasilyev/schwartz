from __future__ import annotations

import httpx
import feedparser
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id, update_source
from app.infrastructure.vk.client import VKApiError, VkNoAccessTokenConfigured, vk_call
from app.presentation.schemas.source import SourceRefreshMetadataResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 15.0


async def execute(db: AsyncSession, source_id: int) -> SourceRefreshMetadataResponse:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    platform = (row.platform or row.source or "").lower()

    if platform == "rss":
        meta = await _fetch_rss_metadata(row.url)
    elif platform == "vk":
        meta = await _fetch_vk_metadata(row.vk_owner_id, row.url)
    else:
        return SourceRefreshMetadataResponse(source_id=source_id, updated=False)

    if meta is None:
        return SourceRefreshMetadataResponse(source_id=source_id, updated=False)

    await update_source(db, source_id, source_metadata=meta)
    return SourceRefreshMetadataResponse(source_id=source_id, updated=True, source_metadata=meta)


async def _fetch_rss_metadata(url: str) -> dict | None:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        feed = feedparser.parse(resp.text)
        feed_info = feed.get("feed", {})
        return {
            "title": feed_info.get("title"),
            "subtitle": feed_info.get("subtitle"),
            "link": feed_info.get("link"),
            "language": feed_info.get("language"),
            "updated": feed_info.get("updated"),
            "generator": feed_info.get("generator"),
            "entry_count": len(feed.get("entries", [])),
        }
    except Exception as exc:
        logger.warning("rss_metadata_error", url=url, error=str(exc))
        return None


async def _fetch_vk_metadata(vk_owner_id: int | None, url: str) -> dict | None:
    if vk_owner_id is None:
        return None
    try:
        group_id = abs(vk_owner_id)
        resp = await vk_call(
            "groups.getById",
            group_ids=str(group_id),
            fields="description,members_count,city,country,site,status,verified",
        )
        groups = resp if isinstance(resp, list) else resp.get("groups", [resp])
        if not groups:
            return None
        g = groups[0]
        return {
            "id": g.get("id"),
            "name": g.get("name"),
            "screen_name": g.get("screen_name"),
            "description": g.get("description"),
            "members_count": g.get("members_count"),
            "verified": g.get("verified"),
            "site": g.get("site"),
            "status": g.get("status"),
            "type": g.get("type"),
        }
    except (VkNoAccessTokenConfigured, VKApiError) as exc:
        logger.warning("vk_metadata_error", vk_owner_id=vk_owner_id, error=str(exc))
        return None
    except Exception as exc:
        logger.warning("vk_metadata_error", vk_owner_id=vk_owner_id, error=str(exc))
        return None
