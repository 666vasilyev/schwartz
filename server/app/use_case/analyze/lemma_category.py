"""GET /analyze/lemma/category/{category_name} — агрегат ЦКМ по постам всех источников категории."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import CSV_COLUMNS, score_text
from app.infrastructure.db.orm.models import Post, SourceCategoryModel, source_category_link
from app.presentation.schemas.analysis import SourceLemmaAnalysisResponse


async def execute(
    db: AsyncSession,
    category_name: str,
    *,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> SourceLemmaAnalysisResponse:
    # Проверяем существование категории
    cat = await db.get(SourceCategoryModel, category_name)
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

    # Посты всех источников категории через junction-таблицу
    q = (
        select(Post)
        .where(
            Post.source_id.in_(
                select(source_category_link.c.source_id).where(
                    source_category_link.c.category_name == category_name
                )
            )
        )
        .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())
    )
    if date_from is not None:
        q = q.where(Post.published_at >= date_from)
    if date_to is not None:
        q = q.where(Post.published_at <= date_to)
    if limit is not None:
        q = q.limit(limit)

    result = await db.execute(q)
    posts = list(result.scalars().all())

    posts_total = len(posts)
    skipped = 0
    vectors: list[dict[str, float]] = []

    for post in posts:
        text = post.text or ""
        if not text.strip():
            skipped += 1
            continue
        scores, _ = score_text(text)
        vectors.append(scores)

    posts_analyzed = len(vectors)

    if not vectors:
        aggregate = {k: 0.0 for k in CSV_COLUMNS}
    else:
        n = len(vectors)
        raw = {k: sum(v[k] for v in vectors) / n for k in CSV_COLUMNS}
        total = sum(raw.values())
        if total > 0:
            aggregate = {k: round(v / total, 4) for k, v in raw.items()}
        else:
            aggregate = {k: 0.0 for k in CSV_COLUMNS}

    return SourceLemmaAnalysisResponse(
        source_id=None,
        category_name=category_name,
        posts_total=posts_total,
        posts_analyzed=posts_analyzed,
        posts_skipped_empty=skipped,
        aggregate_schwartz=aggregate,
    )
