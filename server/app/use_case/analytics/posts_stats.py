"""
GET /api/v1/analytics/posts/stats — статистика собранных постов: за сутки /
неделю / месяц / всего. Считается по created_at (момент сохранения в БД), а не
published_at (дата публикации на источнике) — см. репозиторную функцию
count_posts_since.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.post import count_posts, count_posts_since
from app.presentation.schemas.analytics import PostsCollectedStatsResponse


async def execute(db: AsyncSession) -> PostsCollectedStatsResponse:
    now = datetime.now(tz=timezone.utc)
    last_24h = await count_posts_since(db, now - timedelta(hours=24))
    last_7d = await count_posts_since(db, now - timedelta(days=7))
    last_30d = await count_posts_since(db, now - timedelta(days=30))
    total = await count_posts(db)
    return PostsCollectedStatsResponse(
        as_of=now,
        last_24h=last_24h,
        last_7d=last_7d,
        last_30d=last_30d,
        total=total,
    )
