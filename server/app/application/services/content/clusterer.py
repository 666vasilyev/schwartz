"""
Онлайн (инкрементальная) сюжетная кластеризация новостей.

Алгоритм single-pass:
  Для каждого нового поста:
    1. Получаем (или считаем) эмбеддинг текста.
    2. Ищем ближайший центроид среди активных кластеров в скользящем окне.
    3. Если cosine similarity >= threshold — добавляем пост в кластер
       и пересчитываем центроид: c' = (c * n + e) / (n + 1).
    4. Иначе — заводим новый кластер с центроидом = e.

Эмбеддинги L2-нормализованы (см. embedder), поэтому в среднем длина центроида
будет близка к 1; для устойчивости считаем "среднее без перенормировки" — этого
достаточно для поиска ближайших по cosine_distance.

Архивация: кластеры с last_seen_at старше окна переводятся в archived, чтобы
не загромождать кандидатов для новых постов.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content import embedder
from app.core.config import get_settings
from app.infrastructure.db.orm.models import Post
from app.infrastructure.repositories import (
    archive_stale_clusters,
    count_posts_in_cluster,
    count_sources_in_cluster,
    create_cluster,
    find_nearest_active_cluster,
    get_assignment_by_post,
    get_cluster_by_id,
    list_posts_missing_embedding,
    upsert_assignment,
    upsert_embedding,
)
from app.infrastructure.repositories.story_cluster import update_cluster_centroid
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


@dataclass
class ClusteringBatchResult:
    processed: int
    new_clusters: int
    extended_clusters: int
    skipped_empty_text: int
    archived_clusters: int


def _running_mean(old_centroid: list[float], n_old: int, new_vec: list[float]) -> list[float]:
    """Онлайн-пересчёт среднего: c' = (c * n + v) / (n + 1)."""
    n_new = n_old + 1
    return [(c * n_old + v) / n_new for c, v in zip(old_centroid, new_vec, strict=True)]


async def cluster_posts_batch(
    db: AsyncSession,
    posts: list[Post],
) -> ClusteringBatchResult:
    """
    Считает эмбеддинги для пачки постов и кластеризует их по одному.

    Контракт по транзакции: вызывающий код владеет сессией и сам коммитит/откатывает.
    Это позволяет интегрировать кластеризацию в существующие use_case без дублирования
    управления сессией.
    """
    model_name = embedder.model_name()
    now = _utcnow()

    # Фильтруем посты с непустым текстом
    valid_posts: list[Post] = []
    skipped_empty = 0
    for p in posts:
        if p.text and p.text.strip():
            valid_posts.append(p)
        else:
            skipped_empty += 1

    if not valid_posts:
        return ClusteringBatchResult(
            processed=0,
            new_clusters=0,
            extended_clusters=0,
            skipped_empty_text=skipped_empty,
            archived_clusters=0,
        )

    # 1. Эмбеддинги одним батчем — это самая дорогая операция
    texts = [p.text or "" for p in valid_posts]
    vectors = await embedder.encode_passages(texts)

    new_clusters = 0
    extended_clusters = 0

    for post, vec in zip(valid_posts, vectors, strict=True):
        text_hash = embedder.text_hash(post.text or "")
        await upsert_embedding(
            db,
            post_id=int(post.id),
            embedding=vec,
            model_name=model_name,
            text_hash=text_hash,
        )

        # Если у поста уже было назначение — не перекластеризуем (идемпотентность для ретраев).
        existing = await get_assignment_by_post(db, int(post.id))
        if existing is not None:
            continue

        # 2. Ищем ближайший подходящий кластер
        match = await find_nearest_active_cluster(
            db,
            embedding=vec,
            model_name=model_name,
            window_days=settings.cluster_window_days,
            similarity_threshold=settings.cluster_similarity_threshold,
            now=now,
        )

        if match is None:
            # 3. Новый сюжет
            cluster = await create_cluster(
                db,
                centroid=vec,
                model_name=model_name,
                now=now,
            )
            await upsert_assignment(
                db,
                post_id=int(post.id),
                cluster_id=int(cluster.id),
                similarity=1.0,
            )
            await update_cluster_centroid(
                db,
                cluster_id=int(cluster.id),
                new_centroid=vec,
                posts_count=1,
                sources_count=1 if post.source_id is not None else 0,
                last_seen_at=post.published_at or now,
            )
            new_clusters += 1
        else:
            # 4. Расширяем существующий
            cluster, similarity = match
            new_centroid = _running_mean(
                list(cluster.centroid), int(cluster.posts_count or 0), vec
            )
            await upsert_assignment(
                db,
                post_id=int(post.id),
                cluster_id=int(cluster.id),
                similarity=similarity,
            )
            new_posts_count = int(cluster.posts_count or 0) + 1
            # Точный пересчёт уникальных источников — после ассайнмента
            sources_count = await count_sources_in_cluster(db, int(cluster.id))
            await update_cluster_centroid(
                db,
                cluster_id=int(cluster.id),
                new_centroid=new_centroid,
                posts_count=new_posts_count,
                sources_count=sources_count,
                last_seen_at=max(
                    cluster.last_seen_at, post.published_at or now
                ),
            )
            extended_clusters += 1

    # 5. Архивация старых
    archived = await archive_stale_clusters(
        db, window_days=settings.cluster_window_days, now=now
    )

    logger.info(
        "clustering_batch_done",
        processed=len(valid_posts),
        new_clusters=new_clusters,
        extended_clusters=extended_clusters,
        archived=archived,
        skipped_empty=skipped_empty,
    )

    return ClusteringBatchResult(
        processed=len(valid_posts),
        new_clusters=new_clusters,
        extended_clusters=extended_clusters,
        skipped_empty_text=skipped_empty,
        archived_clusters=archived,
    )


async def cluster_unprocessed_posts(db: AsyncSession) -> ClusteringBatchResult:
    """
    Высокоуровневая обёртка: берёт N постов без эмбеддинга для текущей модели
    и кластеризует их. Используется фоновой задачей и эндпоинтом ручного запуска.
    """
    posts = await list_posts_missing_embedding(
        db,
        model_name=embedder.model_name(),
        limit=settings.clustering_batch_size,
    )
    return await cluster_posts_batch(db, posts)
