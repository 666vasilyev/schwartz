"""
Общая сборка list[TrendingClusterItem] для всех trending-эндпоинтов
(/trending, /trending/by-source, /trending/by-category):
  1. Lazy-доразметка кластеров без title/summary/topics через LLM.
  2. Подтяжка первоисточника (источник + дата самого раннего поста кластера).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.cluster_labeler import label_missing_in_rows
from app.infrastructure.db.orm.models import StoryCluster
from app.infrastructure.repositories import list_first_sources
from app.presentation.schemas.cluster import (
    ClusterFirstSource,
    ClusterRead,
    TrendingClusterItem,
)


async def build_trending_items(
    db: AsyncSession,
    rows: list[tuple[StoryCluster, int, int]],
) -> list[TrendingClusterItem]:
    # Lazy-доразметка: кластеры без title/summary/topics размечаются через LLM
    # прямо здесь, конкурентно, перед отдачей ответа.
    await label_missing_in_rows(db, rows)

    cluster_ids = [int(cluster.id) for cluster, _, _ in rows]
    first_sources = await list_first_sources(db, cluster_ids)

    items: list[TrendingClusterItem] = []
    for cluster, posts_w, sources_w in rows:
        fs = first_sources.get(int(cluster.id))
        first_source = (
            ClusterFirstSource(
                source_id=fs[0],
                source_name=fs[1],
                first_published_at=fs[2],
            )
            if fs is not None
            else None
        )
        items.append(
            TrendingClusterItem(
                cluster=ClusterRead.model_validate(cluster),
                posts_in_window=posts_w,
                sources_in_window=sources_w,
                first_source=first_source,
            )
        )
    return items
