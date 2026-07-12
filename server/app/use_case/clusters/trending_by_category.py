"""GET /api/v1/clusters/trending/by-category — тренды в рамках одной или нескольких категорий источников."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.cluster_labeler import label_missing_in_rows
from app.infrastructure.repositories import list_trending_by_categories
from app.presentation.schemas.cluster import (
    CategoryTrendingClustersResponse,
    ClusterRead,
    TrendingClusterItem,
)


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
    # Lazy-доразметка: кластеры без title/summary/topics размечаются через LLM
    # прямо здесь, конкурентно, перед отдачей ответа.
    await label_missing_in_rows(db, rows)
    items = [
        TrendingClusterItem(
            cluster=ClusterRead.model_validate(cluster),
            posts_in_window=posts_w,
            sources_in_window=sources_w,
        )
        for cluster, posts_w, sources_w in rows
    ]
    return CategoryTrendingClustersResponse(
        items=items,
        window_hours=window_hours,
        min_posts=min_posts,
        category_names=category_names,
    )
