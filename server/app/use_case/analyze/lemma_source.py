"""GET /analyze/lemma/source/{source_id} — агрегат ЦКМ по постам источника через словарный метод."""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import CSV_COLUMNS, LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post, Source
from app.presentation.schemas.analysis import SourceLemmaAnalysisResponse
from app.use_case.analyze._lemma_aggregate import aggregate_vectors


async def execute(
    db: AsyncSession,
    source_id: int,
    *,
    lang: LemmaLang = LemmaLang.ru,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> SourceLemmaAnalysisResponse:
    src = await db.get(Source, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    q = (
        select(Post)
        .where(Post.source_id == source_id)
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
    non_empty = [(i, t) for i, t in enumerate(texts) if t.strip()]
    skipped = len(texts) - len(non_empty)

    scores_list = await score_texts_batch([t for _, t in non_empty], lang)
    vectors = [s for s, _ in scores_list]

    return SourceLemmaAnalysisResponse(
        source_id=source_id,
        posts_total=len(posts),
        posts_analyzed=len(vectors),
        posts_skipped_empty=skipped,
        aggregate_schwartz=aggregate_vectors(vectors),
    )
