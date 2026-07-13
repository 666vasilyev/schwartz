"""Репозиторий сюжетных кластеров и назначений постов кластерам."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import and_, delete, func, select, update
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import (
    Post,
    PostClusterAssignment,
    Source,
    StoryCluster,
    StoryClusterStatus,
    source_category_link,
)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Создание / поиск ───────────────────────────────────────────────────────


async def create_cluster(
    db: AsyncSession,
    *,
    centroid: list[float],
    model_name: str,
    now: datetime | None = None,
) -> StoryCluster:
    now = now or _utcnow()
    cluster = StoryCluster(
        centroid=centroid,
        model_name=model_name,
        status=StoryClusterStatus.ACTIVE.value,
        posts_count=0,
        sources_count=0,
        first_seen_at=now,
        last_seen_at=now,
    )
    db.add(cluster)
    await db.flush()
    await db.refresh(cluster)
    return cluster


async def get_cluster_by_id(db: AsyncSession, cluster_id: int) -> StoryCluster | None:
    res = await db.execute(select(StoryCluster).where(StoryCluster.id == cluster_id))
    return res.scalar_one_or_none()


async def find_nearest_active_cluster(
    db: AsyncSession,
    *,
    embedding: list[float],
    model_name: str,
    window_days: int,
    similarity_threshold: float,
    max_cluster_size: int | None = None,
    now: datetime | None = None,
) -> tuple[StoryCluster, float] | None:
    """
    Найти ближайший по cosine активный кластер для эмбеддинга в скользящем окне.
    Возвращает (cluster, similarity) если similarity >= threshold, иначе None.

    max_cluster_size — если задан, кластеры с posts_count >= max_cluster_size
    исключаются из кандидатов (страховка от неограниченно растущих "хабов",
    см. docstring модуля clusterer.py).

    pgvector: <=> — cosine distance (0..2). similarity = 1 - distance.
    """
    now = now or _utcnow()
    window_start = now - timedelta(days=window_days)

    distance = StoryCluster.centroid.cosine_distance(embedding).label("distance")
    stmt = (
        select(StoryCluster, distance)
        .where(StoryCluster.status == StoryClusterStatus.ACTIVE.value)
        .where(StoryCluster.model_name == model_name)
        .where(StoryCluster.last_seen_at >= window_start)
    )
    if max_cluster_size is not None:
        stmt = stmt.where(StoryCluster.posts_count < max_cluster_size)
    stmt = stmt.order_by(distance.asc()).limit(1)
    row = (await db.execute(stmt)).first()
    if row is None:
        return None
    cluster, dist = row
    similarity = 1.0 - float(dist)
    if similarity < similarity_threshold:
        return None
    return cluster, similarity


# ── Обновление центроида / счётчиков ───────────────────────────────────────


async def update_cluster_centroid(
    db: AsyncSession,
    *,
    cluster_id: int,
    new_centroid: list[float],
    posts_count: int,
    sources_count: int,
    last_seen_at: datetime,
) -> None:
    await db.execute(
        update(StoryCluster)
        .where(StoryCluster.id == cluster_id)
        .values(
            centroid=new_centroid,
            posts_count=posts_count,
            sources_count=sources_count,
            last_seen_at=last_seen_at,
        )
    )


async def update_cluster_labels(
    db: AsyncSession,
    *,
    cluster_id: int,
    title: str | None,
    summary: str | None,
    topics: list[str] | None,
) -> None:
    await db.execute(
        update(StoryCluster)
        .where(StoryCluster.id == cluster_id)
        .values(
            title=title,
            summary=summary,
            topics=topics,
            labels_updated_at=_utcnow(),
        )
    )


async def archive_stale_clusters(
    db: AsyncSession,
    *,
    window_days: int,
    now: datetime | None = None,
) -> int:
    """Перевести в archived все активные кластеры с last_seen_at старше окна."""
    now = now or _utcnow()
    cutoff = now - timedelta(days=window_days)
    res = await db.execute(
        update(StoryCluster)
        .where(StoryCluster.status == StoryClusterStatus.ACTIVE.value)
        .where(StoryCluster.last_seen_at < cutoff)
        .values(status=StoryClusterStatus.ARCHIVED.value)
    )
    return int(res.rowcount or 0)


# ── Назначения постов кластерам ───────────────────────────────────────────


async def upsert_assignment(
    db: AsyncSession,
    *,
    post_id: int,
    cluster_id: int,
    similarity: float,
) -> None:
    stmt = pg_insert(PostClusterAssignment).values(
        post_id=post_id,
        cluster_id=cluster_id,
        similarity=similarity,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PostClusterAssignment.post_id],
        set_={
            "cluster_id": stmt.excluded.cluster_id,
            "similarity": stmt.excluded.similarity,
        },
    )
    await db.execute(stmt)


async def get_assignment_by_post(
    db: AsyncSession, post_id: int
) -> PostClusterAssignment | None:
    res = await db.execute(
        select(PostClusterAssignment).where(PostClusterAssignment.post_id == post_id)
    )
    return res.scalar_one_or_none()


async def list_posts_without_assignment(
    db: AsyncSession, *, limit: int
) -> list[Post]:
    """
    Посты с непустым текстом, у которых ещё нет назначения в кластер.

    Это основной селектор "что кластеризовать дальше" — и для фонового тика,
    и для rebuild. Раньше вместо этого использовался list_posts_missing_embedding
    ("нет эмбеддинга") — но после rebuild(clear=True) assignments стираются,
    а embeddings нарочно остаются (не пересчитываем зря), из-за чего такие
    посты переставали быть "missing embedding" и НИКОГДА больше не подхватывались
    ни фоновым раннером, ни повторным rebuild — кластеризация тихо останавливалась
    насовсем. Проверка "нет назначения" верна в обоих случаях независимо от того,
    есть эмбеддинг или нет (см. cluster_posts_batch — досчитывает эмбеддинг сам,
    если его ещё нет).
    """
    res = await db.execute(
        select(Post)
        .outerjoin(
            PostClusterAssignment, PostClusterAssignment.post_id == Post.id
        )
        .where(Post.text.isnot(None))
        .where(Post.text != "")
        .where(PostClusterAssignment.post_id.is_(None))
        .order_by(Post.id.asc())
        .limit(limit)
    )
    return list(res.scalars().all())


async def count_posts_in_cluster(db: AsyncSession, cluster_id: int) -> int:
    res = await db.execute(
        select(func.count()).where(PostClusterAssignment.cluster_id == cluster_id)
    )
    return int(res.scalar_one() or 0)


async def count_sources_in_cluster(db: AsyncSession, cluster_id: int) -> int:
    res = await db.execute(
        select(func.count(func.distinct(Post.source_id)))
        .select_from(PostClusterAssignment)
        .join(Post, Post.id == PostClusterAssignment.post_id)
        .where(PostClusterAssignment.cluster_id == cluster_id)
    )
    return int(res.scalar_one() or 0)


async def list_posts_in_cluster(
    db: AsyncSession,
    cluster_id: int,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[Post]:
    res = await db.execute(
        select(Post)
        .join(PostClusterAssignment, PostClusterAssignment.post_id == Post.id)
        .where(PostClusterAssignment.cluster_id == cluster_id)
        .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())
        .offset(skip)
        .limit(limit)
    )
    return list(res.scalars().all())


# ── Списки и тренды ────────────────────────────────────────────────────────


def _apply_cluster_filters(
    q,
    *,
    status: str | None = None,
    min_posts: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
):
    if status is not None:
        q = q.where(StoryCluster.status == status)
    if min_posts is not None and min_posts > 0:
        q = q.where(StoryCluster.posts_count >= min_posts)
    if date_from is not None:
        q = q.where(StoryCluster.last_seen_at >= date_from)
    if date_to is not None:
        q = q.where(StoryCluster.last_seen_at <= date_to)
    return q


async def list_clusters(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    status: str | None = StoryClusterStatus.ACTIVE.value,
    min_posts: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[StoryCluster]:
    q = (
        select(StoryCluster)
        .order_by(StoryCluster.last_seen_at.desc(), StoryCluster.id.desc())
    )
    q = _apply_cluster_filters(
        q,
        status=status,
        min_posts=min_posts,
        date_from=date_from,
        date_to=date_to,
    )
    q = q.offset(skip).limit(limit)
    res = await db.execute(q)
    return list(res.scalars().all())


async def count_clusters(
    db: AsyncSession,
    *,
    status: str | None = StoryClusterStatus.ACTIVE.value,
    min_posts: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> int:
    q = select(func.count()).select_from(StoryCluster)
    q = _apply_cluster_filters(
        q,
        status=status,
        min_posts=min_posts,
        date_from=date_from,
        date_to=date_to,
    )
    res = await db.execute(q)
    return int(res.scalar_one() or 0)


async def list_trending_combined(
    db: AsyncSession,
    *,
    source_ids: list[int] | None = None,
    category_names: list[str] | None = None,
    window_hours: int = 24,
    min_posts: int = 3,
    limit: int = 20,
    now: datetime | None = None,
    use_published_at: bool = False,
    require_active: bool = True,
) -> list[tuple[StoryCluster, int, int]]:
    """
    Единая точка входа для всех trending-выборок (общие тренды / по источникам /
    по категориям / по пересечению обоих / ретроспектива на дату в прошлом).

    source_ids и category_names — независимые множества-фильтры, которые
    объединяются между собой через AND, а элементы ВНУТРИ каждого множества —
    через OR (union):
      - пустые оба → фильтров нет, общие тренды по всем источникам;
      - задан только source_ids → тренды по объединённому пулу постов этих
        источников (как раньше в /trending/by-source);
      - задан только category_names → тренды по объединённому пулу постов
        источников этих категорий (как раньше в /trending/by-category);
      - заданы оба → тренды по постам источников, которые ОДНОВРЕМЕННО входят
        в source_ids И относятся хотя бы к одной из category_names.

    use_published_at / require_active — переключатель live vs ретроспектива:
      - live (по умолчанию): окно считается по PostClusterAssignment.assigned_at
        (момент, когда наш пайплайн обработал пост) и учитываются только
        status == active кластеры — это подходящее приближение, когда посты
        обрабатываются вскоре после публикации.
      - ретроспектива (use_published_at=True, require_active=False): окно
        считается по Post.published_at (реальная дата публикации), а фильтр по
        статусу снят — иначе после rebuild'а или просто со временем почти все
        кластеры интересующего периода уже archived и результат будет пустым.
        Важная оговорка: кластеры — стейтфул объекты (центроид дрейфует,
        возможен сплит по cluster_max_size), поэтому ретроспектива показывает
        посты даты X, сгруппированные по ИХ ТЕКУЩЕЙ принадлежности к кластеру,
        а не точную картину, которая была бы видна при live-запросе в тот день.

    Оба режима используют один и тот же now/window_hours: для ретроспективы
    now — конец нужного периода, window_hours — его ширина в часах.

    posts_in_window/sources_in_window считаются через distinct — join с
    source_category_link может размножить строки, если источник состоит сразу
    в нескольких запрошенных категориях.
    """
    now = now or _utcnow()
    window_start = now - timedelta(hours=window_hours)

    posts_in_window = func.count(func.distinct(PostClusterAssignment.post_id)).label(
        "posts_in_window"
    )
    sources_in_window = func.count(func.distinct(Post.source_id)).label(
        "sources_in_window"
    )
    time_column = Post.published_at if use_published_at else PostClusterAssignment.assigned_at

    stmt = (
        select(StoryCluster, posts_in_window, sources_in_window)
        .join(
            PostClusterAssignment,
            PostClusterAssignment.cluster_id == StoryCluster.id,
        )
        .join(Post, Post.id == PostClusterAssignment.post_id)
        .where(time_column >= window_start)
        .where(time_column <= now)
    )

    if require_active:
        stmt = stmt.where(StoryCluster.status == StoryClusterStatus.ACTIVE.value)

    if category_names:
        stmt = stmt.join(
            source_category_link,
            source_category_link.c.source_id == Post.source_id,
        ).where(source_category_link.c.category_name.in_(category_names))

    if source_ids:
        stmt = stmt.where(Post.source_id.in_(source_ids))

    stmt = (
        stmt.group_by(StoryCluster.id)
        .having(func.count(func.distinct(PostClusterAssignment.post_id)) >= min_posts)
        .order_by(posts_in_window.desc(), sources_in_window.desc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return [(c, int(pw), int(sw)) for c, pw, sw in res.all()]


async def list_first_sources(
    db: AsyncSession, cluster_ids: list[int]
) -> dict[int, tuple[int | None, str | None, datetime | None]]:
    """
    Первоисточник сюжета: для каждого cluster_id — источник и дата публикации
    самого раннего (по published_at) поста в кластере. Считается по ВСЕМ постам
    кластера, а не только по попавшим в окно trending-выборки.

    Возвращает {cluster_id: (source_id, source_name, published_at)}.
    """
    if not cluster_ids:
        return {}

    stmt = (
        select(
            PostClusterAssignment.cluster_id,
            Post.source_id,
            Source.name,
            Post.published_at,
        )
        .select_from(PostClusterAssignment)
        .join(Post, Post.id == PostClusterAssignment.post_id)
        .outerjoin(Source, Source.id == Post.source_id)
        .where(PostClusterAssignment.cluster_id.in_(cluster_ids))
        .distinct(PostClusterAssignment.cluster_id)
        .order_by(
            PostClusterAssignment.cluster_id,
            Post.published_at.asc().nulls_last(),
            Post.id.asc(),
        )
    )
    res = await db.execute(stmt)
    return {
        int(cluster_id): (source_id, source_name, published_at)
        for cluster_id, source_id, source_name, published_at in res.all()
    }


# ── Тексты постов кластера (для генерации title/summary) ──────────────────


async def list_cluster_post_texts(
    db: AsyncSession, cluster_id: int, *, limit: int = 5
) -> list[str]:
    """Несколько свежих текстов из кластера — для LLM-разметки сюжета."""
    res = await db.execute(
        select(Post.text)
        .join(PostClusterAssignment, PostClusterAssignment.post_id == Post.id)
        .where(PostClusterAssignment.cluster_id == cluster_id)
        .where(Post.text.isnot(None))
        .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())
        .limit(limit)
    )
    return [t for t in res.scalars().all() if t]


async def delete_all_clustering_data(db: AsyncSession) -> None:
    """Полная очистка перед rebuild (assignments → clusters → embeddings не трогаем)."""
    await db.execute(delete(PostClusterAssignment))
    await db.execute(delete(StoryCluster))
