"""
GET /analyze/lemma/categories/combined — ЦКМ по ОДНОМУ объединённому пулу постов
из списка категорий (словарный метод), с разбивкой по леммам на каждый параметр.

В отличие от lemma_categories.py (POST /lemma/categories — список результатов,
по одному на категорию), здесь всегда ровно один результат на весь запрос:
источники, входящие сразу в несколько запрошенных категорий, учитываются один
раз (union, дедуп через IN-подзапрос — как в lemma_category.py, а не JOIN, как
в lemma_categories.py, где JOIN размножил бы строки постов таких источников).
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import (
    CSV_COLUMNS,
    LemmaLang,
    score_texts_batch_explained,
)
from app.infrastructure.db.orm.models import Post, source_category_link
from app.presentation.schemas.analysis import (
    CategoriesLemmaCkmResponse,
    LemmaDimensionScore,
)
from app.use_case.analyze._lemma_aggregate import (
    aggregate_dimension_lemmas,
    aggregate_vectors,
)


async def execute(
    db: AsyncSession,
    category_names: list[str],
    *,
    lang: LemmaLang = LemmaLang.ru,
    top_n_lemmas: int = 15,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> CategoriesLemmaCkmResponse:
    q = (
        select(Post)
        .where(
            Post.source_id.in_(
                select(source_category_link.c.source_id).where(
                    source_category_link.c.category_name.in_(category_names)
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
        # limit — на весь объединённый пул, а не на каждую категорию отдельно
        # (в отличие от POST /lemma/categories, где лимит применяется per-category).
        q = q.limit(limit)

    result = await db.execute(q)
    posts = list(result.scalars().all())

    texts = [p.text or "" for p in posts]
    non_empty = [t for t in texts if t.strip()]
    skipped = len(texts) - len(non_empty)

    scores_list = await score_texts_batch_explained(non_empty, lang)
    vectors = [s for s, _dl, _c in scores_list]
    dim_lemmas_list = [dl for _s, dl, _c in scores_list]

    aggregate = aggregate_vectors(vectors)
    dim_lemmas = aggregate_dimension_lemmas(dim_lemmas_list, top_n=top_n_lemmas)

    values = {
        col: LemmaDimensionScore(score=aggregate[col], lemmas=dim_lemmas.get(col, []))
        for col in CSV_COLUMNS
    }

    return CategoriesLemmaCkmResponse(
        category_names=category_names,
        lang=lang,
        posts_total=len(posts),
        posts_analyzed=len(vectors),
        posts_skipped_empty=skipped,
        values=values,
    )
