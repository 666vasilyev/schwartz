"""GET /api/v1/clusters/trending — трендовые сюжеты за окно."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import list_trending
from app.presentation.schemas.cluster import TrendingClustersResponse
from app.use_case.clusters._trending_common import build_trending_items


async def execute(
    db: AsyncSession,
    *,
    window_hours: int,
    min_posts: int,
    limit: int,
) -> TrendingClustersResponse:
    rows = await list_trending(
        db,
        window_hours=window_hours,
        min_posts=min_posts,
        limit=limit,
    )
    items = await build_trending_items(db, rows)
    return TrendingClustersResponse(
        items=items,
        window_hours=window_hours,
        min_posts=min_posts,
    )
