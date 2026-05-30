"""VK wall fetch use cases: incremental, period-based, preview."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, Source
from app.infrastructure.repositories.source import get_source_by_id, update_source
from app.infrastructure.vk.wall import (
    WallCollectResult,
    collect_by_limit,
    collect_by_period,
    collect_incremental,
    latest_post_id,
)
from app.presentation.schemas.vk import (
    VkFetchPreviewRequest,
    VkFetchPreviewResponse,
    VkFetchRequest,
    VkFetchResult,
    VkHistoricalFetchRequest,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _get_vk_source(db: AsyncSession, source_id: int) -> Source:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if src.source_type != "vk":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Источник не является VK-источником",
        )
    if not src.vk_owner_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="owner_id не заполнен для источника",
        )
    return src


async def _persist_posts(db: AsyncSession, src: Source, result: WallCollectResult) -> tuple[int, int]:
    """Upsert normalized posts into the posts table. Returns (saved, duplicate)."""
    saved = 0
    duplicate = 0
    for post in result.posts:
        if post.get("deleted"):
            continue
        vk_post_id = post.get("vk_post_id")
        if not vk_post_id:
            continue
        existing = await db.scalar(
            select(Post).where(Post.vk_post_id == vk_post_id)
        )
        if existing:
            duplicate += 1
            continue
        row = Post(
            source_id=src.id,
            vk_post_id=vk_post_id,
            owner_id=post.get("owner_id"),
            text=post.get("text"),
            published_at=post.get("published_dt"),
            is_ad=bool(post.get("is_ad")),
            reactions=post.get("reactions"),
            attachments=post.get("attachments"),
            payload=post,
        )
        db.add(row)
        saved += 1
    await db.flush()
    return saved, duplicate


async def fetch(
    db: AsyncSession,
    source_id: int,
    body: VkFetchRequest,
) -> VkFetchResult:
    src = await _get_vk_source(db, source_id)
    meta = dict(src.source_metadata or {})
    since_post_id = meta.get("last_vk_post_id")

    result = await collect_incremental(
        src.vk_owner_id,
        since_post_id=since_post_id,
        max_posts=body.limit,
        skip_ads=body.skip_ads,
    )

    saved, duplicate = await _persist_posts(db, src, result)

    new_latest = latest_post_id(result) or since_post_id
    meta["last_vk_post_id"] = new_latest
    meta["total_collected"] = int(meta.get("total_collected") or 0) + saved

    now = _utcnow()
    await update_source(
        db,
        source_id,
        source_metadata=meta,
        last_fetch_at=now,
        last_success_at=now,
        error_count=0,
    )

    logger.info(
        "vk_fetch_done",
        source_id=source_id,
        fetched=result.fetched_count,
        saved=saved,
        stopped_by=result.stopped_by,
    )
    return VkFetchResult(
        source_id=source_id,
        owner_id=src.vk_owner_id,
        fetched_count=result.fetched_count,
        saved_count=saved,
        duplicate_count=duplicate,
        stopped_by=result.stopped_by,
        latest_post_id=str(new_latest) if new_latest else None,
    )


async def fetch_historical(
    db: AsyncSession,
    source_id: int,
    body: VkHistoricalFetchRequest,
) -> VkFetchResult:
    src = await _get_vk_source(db, source_id)

    date_from = body.date_from
    if date_from.tzinfo is None:
        date_from = date_from.replace(tzinfo=timezone.utc)
    date_to = body.date_to
    if date_to is not None and date_to.tzinfo is None:
        date_to = date_to.replace(tzinfo=timezone.utc)

    result = await collect_by_period(
        src.vk_owner_id,
        date_from=date_from,
        date_to=date_to,
        max_posts=body.max_posts,
        skip_ads=body.skip_ads,
    )

    saved, duplicate = await _persist_posts(db, src, result)

    now = _utcnow()
    await update_source(
        db,
        source_id,
        last_fetch_at=now,
        last_success_at=now,
        error_count=0,
    )

    return VkFetchResult(
        source_id=source_id,
        owner_id=src.vk_owner_id,
        fetched_count=result.fetched_count,
        saved_count=saved,
        duplicate_count=duplicate,
        stopped_by=result.stopped_by,
        latest_post_id=latest_post_id(result),
    )


async def fetch_preview(
    db: AsyncSession,
    source_id: int,
    body: VkFetchPreviewRequest,
) -> VkFetchPreviewResponse:
    src = await _get_vk_source(db, source_id)

    result = await collect_by_limit(
        src.vk_owner_id,
        limit=body.limit,
        skip_ads=body.skip_ads,
    )

    posts_out = []
    for post in result.posts:
        p = {k: v for k, v in post.items() if k != "published_dt"}
        posts_out.append(p)

    return VkFetchPreviewResponse(
        owner_id=src.vk_owner_id,
        posts=posts_out,
        fetched_count=result.fetched_count,
    )
