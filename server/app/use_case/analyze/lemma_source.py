"""POST /analyze/lemma/source — агрегат ЦКМ по списку источников через словарный метод."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post
from app.presentation.schemas.analysis import SourceLemmaAnalysisResponse
from app.use_case.analyze._lemma_aggregate import aggregate_categories, aggregate_vectors


async def execute(
    db: AsyncSession,
    source_ids: list[int],
    *,
    lang: LemmaLang = LemmaLang.ru,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SourceLemmaAnalysisResponse]:
    # Один запрос для всех источников — AsyncSession не поддерживает конкурентные запросы
    q = (
        select(Post)
        .where(Post.source_id.in_(source_ids))
        .order_by(Post.source_id, Post.published_at.desc().nulls_last(), Post.id.desc())
    )
    if date_from is not None:
        q = q.where(Post.published_at >= date_from)
    if date_to is not None:
        q = q.where(Post.published_at <= date_to)

    result = await db.execute(q)
    all_posts = list(result.scalars().all())

    # Группируем по source_id, применяем limit на каждый
    posts_by_source: dict[int, list[Post]] = defaultdict(list)
    for post in all_posts:
        sid = post.source_id
        if sid in source_ids:
            if limit is None or len(posts_by_source[sid]) < limit:
                posts_by_source[sid].append(post)

    # Параллельный scoring (CPU-bound, threadpool) — без DB, только текст
    results: list[SourceLemmaAnalysisResponse] = []
    for sid in source_ids:
        posts = posts_by_source.get(sid, [])
        texts = [p.text or "" for p in posts]
        non_empty = [t for t in texts if t.strip()]
        skipped = len(texts) - len(non_empty)

        scores_list = await score_texts_batch(non_empty, lang)
        vectors = [s for s, _, _c in scores_list]
        cat_freqs = [c for _s, _, c in scores_list]

        results.append(SourceLemmaAnalysisResponse(
            source_id=sid,
            posts_total=len(posts),
            posts_analyzed=len(vectors),
            posts_skipped_empty=skipped,
            aggregate_schwartz=aggregate_vectors(vectors),
            aggregate_categories=aggregate_categories(cat_freqs),
        ))

    return results
