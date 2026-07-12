"""
POST /api/v1/clusters/rebuild — полная перестройка сюжетных кластеров.

Сбрасывает все назначения + сами кластеры (эмбеддинги не трогаем) и заново
прогоняет все посты через single-pass clusterer пачками. Полезно после смены
параметров (threshold, окно) или модели эмбеддингов.

Отбор "необработанных" постов идёт по отсутствию назначения в кластер
(list_posts_without_assignment), а не по отсутствию эмбеддинга: после
delete_all_clustering_data() эмбеддинги намеренно сохраняются (их пересчёт —
самая дорогая часть), поэтому проверка "нет эмбеддинга" после clear=True
находила бы 0 постов и rebuild молча завершался бы, ничего не обработав.
cluster_posts_batch сам досчитывает эмбеддинг для постов, у которых его
действительно ещё нет.

Внимание: даже на 1k постов в день это N пачек × encode() — может занять
заметное время. По умолчанию работает синхронно в рамках HTTP-запроса;
если процесс долгий — стоит вынести в фоновую CollectionJob (TODO).
"""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.clusterer import cluster_unprocessed_posts
from app.core.config import get_settings
from app.infrastructure.repositories import delete_all_clustering_data
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
            # list_posts_without_assignment уже сама фильтрует посты с пустым
            # текстом, так что processed=0 однозначно означает "больше нечего
            # обрабатывать" — без риска зациклиться на постах с пустым текстом.
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
