"""
GET /api/v1/analytics/posts/daily — динамика собранных постов по дням (для
графика): каждой дате диапазона — количество постов, собранных в эту дату
(по created_at). Дни без постов возвращаются с count=0, а не пропускаются —
чтобы график не "скакал" по оси X.
"""
from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.post import count_posts_by_day
from app.presentation.schemas.analytics import PostsDailyPoint, PostsDailyResponse
from app.utils.date_range import utc_day_range


async def execute(
    db: AsyncSession,
    *,
    date_from: date,
    date_to: date,
) -> PostsDailyResponse:
    start, end = utc_day_range(date_from, date_to)
    rows = await count_posts_by_day(db, date_from=start, date_to=end)
    counts_by_day = {day: cnt for day, cnt in rows}

    points: list[PostsDailyPoint] = []
    current = date_from
    while current <= date_to:
        points.append(PostsDailyPoint(date=current, count=counts_by_day.get(current, 0)))
        current += timedelta(days=1)

    return PostsDailyResponse(date_from=date_from, date_to=date_to, points=points)
