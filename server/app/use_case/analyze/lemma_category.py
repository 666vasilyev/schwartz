"""GET /analyze/lemma/category/{category_name} — агрегат ЦКМ по постам всех источников категории."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post, SourceCategoryModel, source_category_link
from app.presentation.schemas.analysis import SourceLemmaAnalysisResponse
from app.use_case.analyze._lemma_aggregate import aggregate_vectors


async def execute(
    db: AsyncSession,
    category_name: str,
    *,
    lang: LemmaLang = LemmaLang.ru,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> SourceLemmaAnalysisResponse:
    cat = await db.get(SourceCategoryModel, category_name)
    if cat is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")

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

    texts = [p.text or "" for p in posts]
    non_empty = [t for t in texts if t.strip()]
    skipped = len(texts) - len(non_empty)

    scores_list = await score_texts_batch(non_empty, lang)
    vectors = [s for s, _ in scores_list]

    return SourceLemmaAnalysisResponse(
        source_id=None,
        category_name=category_name,
        posts_total=len(posts),
        posts_analyzed=len(vectors),
        posts_skipped_empty=skipped,
        aggregate_schwartz=aggregate_vectors(vectors),
    )
