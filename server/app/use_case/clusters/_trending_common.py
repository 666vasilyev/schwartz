"""
Общая сборка list[TrendingClusterItem] для всех trending-эндпоинтов
(/trending, /trending/by-source, /trending/by-category):
  1. Lazy-доразметка кластеров без title/summary/topics через LLM.
  2. Подтяжка первоисточника (источник + дата самого раннего поста кластера).
  3. new_lemmas — самые частые леммы в постах каждого кластера за то же окно,
     что использовалось для расчёта тренда (простой список, как topics).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.cluster_labeler import label_missing_in_rows
from app.application.services.content.lemma_frequency import top_frequent_lemmas
from app.application.services.content.lemma_scorer import LemmaLang
from app.infrastructure.db.orm.models import StoryCluster
from app.infrastructure.repositories import list_first_sources, list_post_texts_by_cluster
from app.presentation.schemas.cluster import (
    ClusterFirstSource,
    ClusterRead,
    TrendingClusterItem,
)


async def build_trending_items(
    db: AsyncSession,
    rows: list[tuple[StoryCluster, int, int]],
    *,
    window_start: datetime,
    window_end: datetime,
    lemma_lang: LemmaLang = LemmaLang.ru,
    lemma_top_n: int = 10,
) -> list[TrendingClusterItem]:
    # Lazy-доразметка: кластеры без title/summary/topics размечаются через LLM
    # прямо здесь, конкурентно, перед отдачей ответа.
    await label_missing_in_rows(db, rows)

    cluster_ids = [int(cluster.id) for cluster, _, _ in rows]
    first_sources = await list_first_sources(db, cluster_ids)
    texts_by_cluster = await list_post_texts_by_cluster(
        db, cluster_ids, date_from=window_start, date_to=window_end
    )

    items: list[TrendingClusterItem] = []
    for cluster, posts_w, sources_w in rows:
        cid = int(cluster.id)
        fs = first_sources.get(cid)
        first_source = (
            ClusterFirstSource(
                source_id=fs[0],
                source_name=fs[1],
                first_published_at=fs[2],
            )
            if fs is not None
            else None
        )
        ranked = top_frequent_lemmas(texts_by_cluster.get(cid, []), lemma_lang, lemma_top_n)
        items.append(
            TrendingClusterItem(
                cluster=ClusterRead.model_validate(cluster),
                posts_in_window=posts_w,
                sources_in_window=sources_w,
                first_source=first_source,
                new_lemmas=[lemma for lemma, _count in ranked],
            )
        )
    return items
