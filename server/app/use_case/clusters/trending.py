"""
GET /api/v1/clusters/trending — единый эндпоинт трендов.

source_ids и category_names — необязательные списки (могут быть пустыми):
  - оба пусты → общие тренды по всем источникам;
  - задан только один → тренд в рамках этого множества (union внутри списка);
  - заданы оба → тренд по пересечению (AND) — источник должен одновременно
    входить в source_ids И относиться хотя бы к одной из category_names.

См. list_trending_combined для деталей SQL-запроса.
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import list_trending_combined
from app.presentation.schemas.cluster import TrendingClustersResponse
from app.use_case.clusters._trending_common import build_trending_items


async def execute(
    db: AsyncSession,
    *,
    source_ids: list[int] | None = None,
    category_names: list[str] | None = None,
    window_hours: int,
    min_posts: int,
    limit: int,
) -> TrendingClustersResponse:
    source_ids = source_ids or []
    category_names = category_names or []

    rows = await list_trending_combined(
        db,
        source_ids=source_ids or None,
        category_names=category_names or None,
        window_hours=window_hours,
        min_posts=min_posts,
        limit=limit,
    )
    items = await build_trending_items(db, rows)
    return TrendingClustersResponse(
        items=items,
        window_hours=window_hours,
        min_posts=min_posts,
        source_ids=source_ids,
        category_names=category_names,
    )
