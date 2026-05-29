"""GET /api/v1/clusters/trending — трендовые сюжеты за окно."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import list_trending
from app.presentation.schemas.cluster import (
    ClusterRead,
    TrendingClusterItem,
    TrendingClustersResponse,
)


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
    items = [
        TrendingClusterItem(
            cluster=ClusterRead.model_validate(cluster),
            posts_in_window=posts_w,
            sources_in_window=sources_w,
        )
        for cluster, posts_w, sources_w in rows
    ]
    return TrendingClustersResponse(
        items=items,
        window_hours=window_hours,
        min_posts=min_posts,
    )
