"""GET /api/v1/clusters/trending/by-category — тренды в рамках одной или нескольких категорий источников."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import list_trending_by_categories
from app.presentation.schemas.cluster import CategoryTrendingClustersResponse
from app.use_case.clusters._trending_common import build_trending_items


async def execute(
    db: AsyncSession,
    *,
    category_names: list[str],
    window_hours: int,
    min_posts: int,
    limit: int,
) -> CategoryTrendingClustersResponse:
    rows = await list_trending_by_categories(
        db,
        category_names=category_names,
        window_hours=window_hours,
        min_posts=min_posts,
        limit=limit,
    )
    items = await build_trending_items(db, rows)
    return CategoryTrendingClustersResponse(
        items=items,
        window_hours=window_hours,
        min_posts=min_posts,
        category_names=category_names,
    )
