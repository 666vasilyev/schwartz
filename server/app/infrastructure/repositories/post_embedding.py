"""Репозиторий эмбеддингов постов."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, PostEmbedding


async def get_embedding(db: AsyncSession, post_id: int) -> PostEmbedding | None:
    res = await db.execute(
        select(PostEmbedding).where(PostEmbedding.post_id == post_id)
    )
    return res.scalar_one_or_none()


async def get_embeddings_by_post_ids(
    db: AsyncSession, post_ids: list[int], *, model_name: str
) -> dict[int, list[float]]:
    """
    Батчевая выборка уже посчитанных эмбеддингов для набора постов (текущей
    модели). Используется кластеризацией, чтобы не пересчитывать эмбеддинги
    для постов, у которых они уже есть (например, после rebuild — там
    assignments/clusters сбрасываются, а embeddings нарочно остаются, т.к.
    их пересчёт — самая дорогая операция).
    """
    if not post_ids:
        return {}
    res = await db.execute(
        select(PostEmbedding.post_id, PostEmbedding.embedding).where(
            PostEmbedding.post_id.in_(post_ids),
            PostEmbedding.model_name == model_name,
        )
    )
    return {pid: list(vec) for pid, vec in res.all()}


async def upsert_embedding(
    db: AsyncSession,
    *,
    post_id: int,
    embedding: list[float],
    model_name: str,
    text_hash: str,
) -> None:
    """
    Идемпотентная запись. Если эмбеддинг уже есть с тем же model_name + text_hash —
    обновлять не надо; если хэш/модель отличаются — перезаписываем.
    """
    stmt = pg_insert(PostEmbedding).values(
        post_id=post_id,
        embedding=embedding,
        model_name=model_name,
        text_hash=text_hash,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[PostEmbedding.post_id],
        set_={
            "embedding": stmt.excluded.embedding,
            "model_name": stmt.excluded.model_name,
            "text_hash": stmt.excluded.text_hash,
        },
    )
    await db.execute(stmt)


async def list_posts_missing_embedding(
    db: AsyncSession,
    *,
    model_name: str,
    limit: int,
) -> list[Post]:
    """
    Посты с непустым текстом, у которых нет валидного эмбеддинга для текущей модели.
    Используется фоновой кластеризацией.
    """
    # LEFT OUTER JOIN на post_embeddings с фильтром по model_name; берём те,
    # где либо строки нет, либо модель другая.
    subq = (
        select(PostEmbedding.post_id)
        .where(PostEmbedding.model_name == model_name)
        .subquery()
    )
    stmt = (
        select(Post)
        .outerjoin(subq, Post.id == subq.c.post_id)
        .where(Post.text.isnot(None))
        .where(Post.text != "")
        .where(subq.c.post_id.is_(None))
        .order_by(Post.id.asc())
        .limit(limit)
    )
    res = await db.execute(stmt)
    return list(res.scalars().all())
