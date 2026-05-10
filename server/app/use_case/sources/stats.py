from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, PostComment
from app.infrastructure.repositories import get_source_by_id
from app.presentation.schemas.source import SourceStats


async def execute(db: AsyncSession, source_id: int) -> SourceStats:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    now = datetime.now(tz=timezone.utc)

    total_posts = await _count_posts(db, source_id, since=None)
    total_comments = await _count_comments(db, source_id)
    posts_24h = await _count_posts(db, source_id, since=now - timedelta(hours=24))
    posts_7d = await _count_posts(db, source_id, since=now - timedelta(days=7))

    return SourceStats(
        source_id=source_id,
        total_posts=total_posts,
        total_comments=total_comments,
        posts_last_24h=posts_24h,
        posts_last_7d=posts_7d,
        last_fetch_at=row.last_fetch_at or row.last_run_at,
        last_success_at=row.last_success_at,
        error_count=row.error_count,
    )


async def _count_posts(
    db: AsyncSession, source_id: int, *, since: datetime | None
) -> int:
    q = select(func.count()).select_from(Post).where(Post.source_id == source_id)
    if since is not None:
        q = q.where(Post.created_at >= since)
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def _count_comments(db: AsyncSession, source_id: int) -> int:
    q = (
        select(func.count())
        .select_from(PostComment)
        .join(Post, PostComment.post_id == Post.id)
        .where(Post.source_id == source_id)
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)
