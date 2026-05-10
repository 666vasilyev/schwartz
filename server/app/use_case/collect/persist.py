from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, SourceStatus
from app.infrastructure.repositories import (
    get_post_by_source_and_external,
    get_post_by_vk_id,
    get_source_by_id,
    replace_comments_from_vk_collect,
    save_post,
    update_source,
    utcnow,
)
from app.presentation.schemas.analysis import VkPostItem
from app.presentation.schemas.collect import (
    CollectRssPublicItem,
    CollectVkPublicPostItem,
    CollectVkPublicResponse,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _vk_collect_payload(item: CollectVkPublicPostItem) -> dict[str, Any]:
    return {
        "published_at": item.published_at,
        "is_ad": item.is_ad,
        "comments": item.comments,
        "reactions": item.reactions,
        "attachments": item.attachments,
    }


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value or not str(value).strip():
        return None
    s = str(value).strip().replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None


async def _apply_vk_collect_to_post(
    db: AsyncSession,
    post_row: Post,
    item: CollectVkPublicPostItem,
    *,
    source_id: int,
) -> None:
    post_row.source_id = source_id
    post_row.vk_post_id = item.vk_post_id
    post_row.owner_id = item.owner_id
    post_row.text = item.text
    post_row.published_at = _parse_iso_datetime(item.published_at)
    post_row.is_ad = item.is_ad
    post_row.reactions = item.reactions if item.reactions else None
    post_row.attachments = item.attachments if item.attachments else None
    post_row.payload = _vk_collect_payload(item)
    await db.flush()
    await replace_comments_from_vk_collect(db, int(post_row.id), item.comments)


def _rss_combined_text(item: CollectRssPublicItem) -> str | None:
    parts: list[str] = []
    if item.title and str(item.title).strip():
        parts.append(str(item.title).strip())
    if item.text and str(item.text).strip():
        parts.append(str(item.text).strip())
    if not parts:
        return None
    return "\n\n".join(parts)


async def persist_vk_public_for_source(
    db: AsyncSession,
    *,
    source_id: int,
    url: str,
    name: str | None,
    vk_owner_id: int,
    posts: list[CollectVkPublicPostItem],
) -> CollectVkPublicResponse:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Источник не найден",
        )
    await update_source(db, src.id, error_message=None)
    await db.commit()
    await db.refresh(src)

    enriched: list[VkPostItem] = []
    saved = 0
    try:
        async with db.begin_nested():
            for item in posts:
                pre: Post | None = None
                if item.vk_post_id:
                    pre = await get_post_by_vk_id(db, item.vk_post_id)
                post_row = await save_post(
                    db,
                    {
                        "source_id": src.id,
                        "vk_post_id": item.vk_post_id,
                        "owner_id": item.owner_id,
                        "text": item.text,
                    },
                )
                await _apply_vk_collect_to_post(db, post_row, item, source_id=src.id)
                if pre is None:
                    saved += 1
                enriched.append(
                    VkPostItem(
                        db_post_id=post_row.id,
                        vk_post_id=item.vk_post_id,
                        owner_id=item.owner_id,
                        text=item.text,
                        published_at=item.published_at,
                        is_ad=item.is_ad,
                        comments=item.comments,
                        reactions=item.reactions,
                        attachments=item.attachments,
                    )
                )
    except Exception as exc:
        await update_source(
            db,
            src.id,
            status=SourceStatus.ERROR.value,
            error_message=str(exc)[:2000],
            last_error_at=utcnow(),
            error_count=src.error_count + 1,
        )
        await db.commit()
        raise

    now = utcnow()
    update_kwargs: dict = dict(
        status=SourceStatus.ACTIVE.value,
        last_run_at=now,
        last_fetch_at=now,
        last_success_at=now,
        error_message=None,
        error_count=0,
        vk_owner_id=vk_owner_id,
    )
    if name is not None:
        update_kwargs["name"] = name
    await update_source(db, src.id, **update_kwargs)
    await db.commit()
    await db.refresh(src)

    logger.info(
        "collect_orchestrate_persisted",
        source_id=src.id,
        vk_owner_id=vk_owner_id,
        n=len(enriched),
    )
    return CollectVkPublicResponse(
        source_id=src.id,
        name=src.name,
        source="vk",
        status=SourceStatus.ACTIVE.value,
        url=url,
        vk_owner_id=vk_owner_id,
        posts=enriched,
        total=len(enriched),
        saved_to_db=saved,
    )


async def persist_rss_public_for_source(
    db: AsyncSession,
    *,
    source_id: int,
    url: str,
    name: str | None,
    feed_title: str | None,
    items: list[CollectRssPublicItem],
) -> CollectVkPublicResponse:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Источник не найден",
        )
    await update_source(db, src.id, error_message=None)
    await db.commit()
    await db.refresh(src)

    enriched: list[VkPostItem] = []
    saved = 0
    try:
        async with db.begin_nested():
            for item in items:
                ext = (item.rss_id or "").strip()
                if not ext:
                    continue
                pre = await get_post_by_source_and_external(db, src.id, ext)
                text = _rss_combined_text(item)
                post_row = await save_post(
                    db,
                    {
                        "source_id": src.id,
                        "external_id": ext,
                        "text": text,
                        "vk_post_id": None,
                        "owner_id": None,
                    },
                )
                if pre is None:
                    saved += 1
                enriched.append(
                    VkPostItem(
                        db_post_id=post_row.id,
                        vk_post_id=ext,
                        owner_id=None,
                        text=text,
                    )
                )
    except Exception as exc:
        await update_source(
            db,
            src.id,
            status=SourceStatus.ERROR.value,
            error_message=str(exc)[:2000],
            last_error_at=utcnow(),
            error_count=src.error_count + 1,
        )
        await db.commit()
        raise

    now = utcnow()
    extra = dict(src.extra) if src.extra else {}
    if feed_title:
        extra["feed_title"] = feed_title
    update_kwargs: dict = dict(
        status=SourceStatus.ACTIVE.value,
        last_run_at=now,
        last_fetch_at=now,
        last_success_at=now,
        error_message=None,
        error_count=0,
        extra=extra,
    )
    if name is not None:
        update_kwargs["name"] = name
    await update_source(db, src.id, **update_kwargs)
    await db.commit()
    await db.refresh(src)

    logger.info("collect_rss_persisted", source_id=src.id, n=len(enriched))
    return CollectVkPublicResponse(
        source_id=src.id,
        name=src.name,
        source="rss",
        status=SourceStatus.ACTIVE.value,
        url=url,
        vk_owner_id=None,
        posts=enriched,
        total=len(enriched),
        saved_to_db=saved,
    )
