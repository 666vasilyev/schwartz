"""
GET /api/v1/analytics/sources/counts — количество источников СМИ: всего и в
разбивке по статусу (active/paused/disabled/error/blocked) и типу платформы
(vk/rss/telegram). Удалённые источники (soft-deleted) не учитываются.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.source import (
    count_sources,
    count_sources_by_status,
    count_sources_by_type,
)
from app.presentation.schemas.analytics import SourceCountsResponse


async def execute(db: AsyncSession) -> SourceCountsResponse:
    total = await count_sources(db, search=None)
    by_status = await count_sources_by_status(db)
    by_type = await count_sources_by_type(db)
    return SourceCountsResponse(total=total, by_status=by_status, by_type=by_type)
