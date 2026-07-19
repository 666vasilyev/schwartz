"""
GET /api/v1/analytics/sources/top — собственное предложение для страницы
Аналитика: топ источников по числу СОБРАННЫХ постов (по created_at) за
опциональный период. Отвечает на вопрос "кто реально поставляет больше всего
контента" — полезно, чтобы заметить как самые продуктивные источники, так и
источники, которые числятся активными, но давно ничего не дают (не попадают
в топ вовсе).
"""
from __future__ import annotations

from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.source import list_top_sources_by_posts
from app.presentation.schemas.analytics import TopSourceItem, TopSourcesResponse
from app.utils.date_range import utc_day_end, utc_day_start


async def execute(
    db: AsyncSession,
    *,
    limit: int = 10,
    date_from: date | None = None,
    date_to: date | None = None,
) -> TopSourcesResponse:
    # date_from/date_to независимы: любой из них может быть не задан (открытая
    # с одной стороны выборка), поэтому границы строятся по отдельности, а не
    # через utc_day_range (которая ожидает обе даты).
    dt_from = utc_day_start(date_from) if date_from else None
    dt_to = utc_day_end(date_to) if date_to else None

    rows = await list_top_sources_by_posts(db, limit=limit, date_from=dt_from, date_to=dt_to)
    items = [
        TopSourceItem(
            source_id=src.id,
            source_name=src.name,
            source_type=src.source_type,
            posts_count=cnt,
        )
        for src, cnt in rows
    ]
    return TopSourcesResponse(date_from=date_from, date_to=date_to, items=items)
