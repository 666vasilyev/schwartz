from __future__ import annotations

from collections.abc import Mapping

import httpx
from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.db.orm.models import Source
from app.infrastructure.repositories import get_source_by_id
from app.presentation.schemas.collect import (
    CollectRssPublicItem,
    CollectVkPublicPostItem,
    CollectVkPublicResponse,
)
from app.use_case.collect import persist
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _collector_headers() -> Mapping[str, str]:
    settings = get_settings()
    secret = (settings.collector_shared_secret or "").strip()
    if not secret:
        return {}
    return {"Authorization": f"Bearer {secret}"}


async def _collect_vk_public(
    db: AsyncSession,
    *,
    row: Source,
    limit: int,
    use_mock: bool,
) -> CollectVkPublicResponse:
    settings = get_settings()
    client_url = f"{settings.collector_base_url.rstrip('/')}/collect/public"
    payload = {
        "name": row.name,
        "url": row.url,
        "limit": limit,
        "use_mock": use_mock,
    }

    hdr = dict(_collector_headers())
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            r = await client.post(client_url, json=payload, headers=hdr)
        except httpx.RequestError as exc:
            logger.error("collect_client_unreachable", url=client_url, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Collector недоступен: {exc!s}",
            ) from exc

    if r.status_code >= 400:
        detail = r.text[:2000] if r.text else r.reason_phrase
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Collector ответил {r.status_code}: {detail}",
        )

    try:
        data = r.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Некорректный JSON от collector: {exc!s}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ответ collector не объект JSON",
        )

    raw_posts = data.get("posts")
    if not isinstance(raw_posts, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="В ответе collector нет поля posts",
        )

    try:
        post_items = [CollectVkPublicPostItem.model_validate(p) for p in raw_posts]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Некорректные элементы posts: {exc!s}",
        ) from exc

    vk_owner_id = data.get("vk_owner_id")
    if vk_owner_id is None:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="В ответе collector нет vk_owner_id",
        )
    url_norm = (data.get("url") or row.url).strip()

    return await persist.persist_vk_public_for_source(
        db,
        source_id=row.id,
        url=url_norm,
        name=row.name,
        vk_owner_id=int(vk_owner_id),
        posts=post_items,
    )


async def _collect_rss(
    db: AsyncSession,
    *,
    row: Source,
    limit: int,
    use_mock: bool,
) -> CollectVkPublicResponse:
    settings = get_settings()
    client_url = f"{settings.collector_base_url.rstrip('/')}/collect/rss"
    payload = {
        "url": row.url,
        "limit": limit,
        "use_mock": use_mock,
    }

    hdr = dict(_collector_headers())
    async with httpx.AsyncClient(timeout=180) as client:
        try:
            r = await client.post(client_url, json=payload, headers=hdr)
        except httpx.RequestError as exc:
            logger.error("collect_rss_unreachable", url=client_url, error=str(exc))
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"Collector недоступен: {exc!s}",
            ) from exc

    if r.status_code >= 400:
        detail = r.text[:2000] if r.text else r.reason_phrase
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Collector ответил {r.status_code}: {detail}",
        )

    try:
        data = r.json()
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Некорректный JSON от collector: {exc!s}",
        ) from exc

    if not isinstance(data, dict):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Ответ collector не объект JSON",
        )

    raw_items = data.get("items")
    if not isinstance(raw_items, list):
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="В ответе collector нет поля items",
        )

    try:
        rss_items = [CollectRssPublicItem.model_validate(p) for p in raw_items]
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Некорректные элементы items: {exc!s}",
        ) from exc

    url_norm = (data.get("url") or row.url).strip()
    feed_title = data.get("feed_title")
    if feed_title is not None:
        feed_title = str(feed_title).strip() or None

    return await persist.persist_rss_public_for_source(
        db,
        source_id=row.id,
        url=url_norm,
        name=row.name,
        feed_title=feed_title,
        items=rss_items,
    )


async def execute(
    db: AsyncSession,
    *,
    source_id: int,
    limit: int,
    use_mock: bool,
) -> CollectVkPublicResponse:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Источник не найден",
        )

    if row.source == "rss":
        return await _collect_rss(db, row=row, limit=limit, use_mock=use_mock)
    return await _collect_vk_public(db, row=row, limit=limit, use_mock=use_mock)
