"""GET /api/v1/clusters/trending/by-source — тренды в рамках одного или нескольких источников."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import list_trending_by_sources
from app.presentation.schemas.cluster import (
    ClusterRead,
    SourceTrendingClustersResponse,
    TrendingClusterItem,
)


async def execute(
    db: AsyncSession,
    *,
    source_ids: list[int],
    window_hours: int,
    min_posts: int,
    limit: int,
) -> SourceTrendingClustersResponse:
    rows = await list_trending_by_sources(
        db,
        source_ids=source_ids,
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
    return SourceTrendingClustersResponse(
        items=items,
        window_hours=window_hours,
        min_posts=min_posts,
        source_ids=source_ids,
    )
