"""
POST /api/v1/clusters/rebuild — полная перестройка сюжетных кластеров.

Сбрасывает все назначения + сами кластеры (эмбеддинги не трогаем) и заново
прогоняет все посты через single-pass clusterer пачками. Полезно после смены
параметров (threshold, окно) или модели эмбеддингов.

Внимание: даже на 1k постов в день это N пачек × encode() — может занять
заметное время. По умолчанию работает синхронно в рамках HTTP-запроса;
если процесс долгий — стоит вынести в фоновую CollectionJob (TODO).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.clusterer import cluster_unprocessed_posts
from app.application.services.content import embedder
from app.core.config import get_settings
from app.infrastructure.repositories import delete_all_clustering_data
from app.infrastructure.repositories.post_embedding import (
    list_posts_missing_embedding,
)
from app.presentation.schemas.cluster import ClusterRebuildResponse

settings = get_settings()


async def execute(db: AsyncSession, *, clear: bool = True) -> ClusterRebuildResponse:
    if clear:
        await delete_all_clustering_data(db)
        await db.flush()

    processed_batches = 0
    total_processed = 0
    total_new = 0
    total_extended = 0

    # Защита от бесконечного цикла: ограничиваем число итераций.
    max_iterations = 10_000

    while True:
        result = await cluster_unprocessed_posts(db)
        if result.processed == 0:
            # Проверим, нет ли вообще постов без эмбеддинга — мог быть только skipped_empty.
            remaining = await list_posts_missing_embedding(
                db,
                model_name=embedder.model_name(),
                limit=1,
            )
            if not remaining:
                break
            # Если что-то осталось, но processed=0 (только пустые тексты) — выходим тоже.
            break

        processed_batches += 1
        total_processed += result.processed
        total_new += result.new_clusters
        total_extended += result.extended_clusters

        if processed_batches >= max_iterations:
            break

    return ClusterRebuildResponse(
        cleared_clusters=clear,
        processed_batches=processed_batches,
        total_processed=total_processed,
        total_new_clusters=total_new,
        total_extended_clusters=total_extended,
    )
