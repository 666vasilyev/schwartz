"""
Онлайн (инкрементальная) сюжетная кластеризация новостей.

Алгоритм single-pass:
  Для каждого нового поста:
    1. Получаем (или считаем) эмбеддинг текста.
    2. Ищем ближайший центроид среди активных кластеров в скользящем окне,
       исключая кластеры, уже достигшие cluster_max_size (см. ниже).
    3. Если cosine similarity >= threshold — добавляем пост в кластер
       и пересчитываем центроид как EMA: c' = alpha*e + (1-alpha)*c.
    4. Иначе — заводим новый кластер с центроидом = e.

EMA вместо running mean по всей истории: раньше центроид считался как
c' = (c*n + e)/(n+1) — при тысячах постов вес нового поста стремится к 0,
центроид "замерзает" на среднем по всей истории кластера. Из-за анизотропии
embedding-пространства такое "среднее по всему" оказывается неожиданно похоже
почти на любой новый текст (hub-эффект) — кластер начинает лавинообразно
поглощать вообще не связанные посты (наблюдалось на проде: один кластер
разросся до тысяч постов из десятков источников на совершенно разные темы).
EMA держит центроид представлением НЕДАВНЕГО содержимого кластера, а не всей
его истории, что решает проблему на уровне причины.

cluster_max_size — дополнительная страховка независимо от качества центроида:
жёсткий потолок, после которого кластер перестаёт принимать новые посты.

Эмбеддинги L2-нормализованы (см. embedder); cosine_distance в pgvector сам
нормализует по длине векторов, так что перенормировка центроида после EMA
не требуется для корректности поиска.

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
    get_embeddings_by_post_ids,
    list_posts_without_assignment,
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


def _ema_update(old_centroid: list[float], new_vec: list[float], *, alpha: float) -> list[float]:
    """
    Экспоненциальное скользящее среднее: c' = alpha*v + (1-alpha)*c.

    В отличие от running mean по всей истории кластера, не "замерзает" при
    большом posts_count — центроид всегда остаётся отражением недавнего
    содержимого, а не усреднением по тысячам исторических постов.
    """
    return [(1.0 - alpha) * c + alpha * v for c, v in zip(old_centroid, new_vec, strict=True)]


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

    # 1. Эмбеддинги: сначала берём уже посчитанные (например, после rebuild —
    # там assignments сбрасываются, а embeddings нарочно остаются), и считаем
    # заново только для постов, у которых их правда ещё нет. Это самая дорогая
    # операция, поэтому важно не пересчитывать то, что уже есть.
    existing_vectors = await get_embeddings_by_post_ids(
        db, [int(p.id) for p in valid_posts], model_name=model_name
    )
    to_encode = [p for p in valid_posts if int(p.id) not in existing_vectors]
    if to_encode:
        new_vectors = await embedder.encode_passages([p.text or "" for p in to_encode])
        for p, vec in zip(to_encode, new_vectors, strict=True):
            existing_vectors[int(p.id)] = vec
            text_hash = embedder.text_hash(p.text or "")
            await upsert_embedding(
                db,
                post_id=int(p.id),
                embedding=vec,
                model_name=model_name,
                text_hash=text_hash,
            )

    new_clusters = 0
    extended_clusters = 0

    for post in valid_posts:
        vec = existing_vectors[int(post.id)]

        # Если у поста уже было назначение — не перекластеризуем (идемпотентность для ретраев).
        existing = await get_assignment_by_post(db, int(post.id))
        if existing is not None:
            continue

        # 2. Ищем ближайший подходящий кластер (кластеры на потолке размера
        # исключаются из кандидатов — см. cluster_max_size)
        match = await find_nearest_active_cluster(
            db,
            embedding=vec,
            model_name=model_name,
            window_days=settings.cluster_window_days,
            similarity_threshold=settings.cluster_similarity_threshold,
            max_cluster_size=settings.cluster_max_size,
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
            new_centroid = _ema_update(
                list(cluster.centroid), vec, alpha=settings.cluster_centroid_ema_alpha
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
    Высокоуровневая обёртка: берёт N постов без назначения в кластер
    и кластеризует их. Используется фоновой задачей и эндпоинтом ручного запуска.

    Раньше отбор шёл по "нет эмбеддинга" (list_posts_missing_embedding), но это
    ломалось после rebuild(clear=True): embeddings там намеренно сохраняются,
    поэтому такие посты никогда не считались "необработанными" и кластеризация
    молча останавливалась. Отбор по "нет назначения" верен независимо от того,
    есть эмбеддинг уже или нет — cluster_posts_batch досчитает недостающие сам.
    """
    posts = await list_posts_without_assignment(
        db,
        limit=settings.clustering_batch_size,
    )
    return await cluster_posts_batch(db, posts)
