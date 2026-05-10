from __future__ import annotations

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id
from app.infrastructure.vk.client import VKApiError, VkNoAccessTokenConfigured, vk_call
from app.infrastructure.vk.vk_public_url import public_path_segment_from_url
from app.presentation.schemas.source import SourceValidateResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TIMEOUT = 10.0


async def execute(db: AsyncSession, source_id: int) -> SourceValidateResponse:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    platform = (row.platform or row.source or "").lower()

    if platform == "rss":
        return await _validate_rss(source_id, row.url)
    elif platform == "vk":
        return await _validate_vk(source_id, row.url, row.vk_owner_id)
    else:
        return await _validate_http(source_id, row.url)


async def _validate_rss(source_id: int, url: str) -> SourceValidateResponse:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(url)
            resp.raise_for_status()
        ct = resp.headers.get("content-type", "")
        if not any(x in ct for x in ("xml", "rss", "atom", "feed")):
            return SourceValidateResponse(
                source_id=source_id,
                reachable=True,
                detail=f"Ответ получен, но Content-Type не RSS/Atom: {ct}",
            )
        return SourceValidateResponse(source_id=source_id, reachable=True)
    except httpx.HTTPError as exc:
        return SourceValidateResponse(source_id=source_id, reachable=False, detail=str(exc))


async def _validate_vk(
    source_id: int, url: str, vk_owner_id: int | None
) -> SourceValidateResponse:
    try:
        if vk_owner_id is not None:
            group_id = abs(vk_owner_id)
            resp = await vk_call("groups.getById", group_ids=str(group_id), fields="description")
            groups = resp if isinstance(resp, list) else resp.get("groups", [resp])
            if groups:
                g = groups[0]
                meta = {
                    "name": g.get("name"),
                    "screen_name": g.get("screen_name"),
                    "members_count": g.get("members_count"),
                }
                return SourceValidateResponse(
                    source_id=source_id, reachable=True, resolved_metadata=meta
                )
        # fallback: resolve screen name
        segment = public_path_segment_from_url(url)
        resp = await vk_call("utils.resolveScreenName", screen_name=segment)
        return SourceValidateResponse(
            source_id=source_id,
            reachable=bool(resp),
            resolved_metadata=resp if resp else None,
        )
    except VkNoAccessTokenConfigured:
        return SourceValidateResponse(
            source_id=source_id,
            reachable=None,  # type: ignore[arg-type]
            detail="Нет токена VK для проверки",
        )
    except VKApiError as exc:
        return SourceValidateResponse(source_id=source_id, reachable=False, detail=str(exc))
    except Exception as exc:
        logger.warning("validate_vk_error", source_id=source_id, error=str(exc))
        return SourceValidateResponse(source_id=source_id, reachable=False, detail=str(exc))


async def _validate_http(source_id: int, url: str) -> SourceValidateResponse:
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.head(url)
        return SourceValidateResponse(
            source_id=source_id,
            reachable=resp.status_code < 400,
            detail=f"HTTP {resp.status_code}",
        )
    except httpx.HTTPError as exc:
        return SourceValidateResponse(source_id=source_id, reachable=False, detail=str(exc))
