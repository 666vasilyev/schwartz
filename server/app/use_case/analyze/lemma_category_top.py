"""
GET /analyze/lemma/category/{category_name}/top — топ категорий лемм и параметров
ЦКМ для ОДНОЙ категории источников (например «Федеральные СМИ»).

В отличие от /lemma/category/{name} (весь словарь долей без обрезки) отдаёт
готовый топ: top_categories (категории лемм из словаря) и top_values (параметры
ЦКМ по убыванию score, у каждого — топ лемм).
"""
from __future__ import annotations

from datetime import datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import (
    CSV_COLUMNS,
    LemmaLang,
    score_texts_batch_explained,
)
from app.infrastructure.db.orm.models import Post, SourceCategoryModel, source_category_link
from app.presentation.schemas.analysis import (
    CategoryShareItem,
    CategoryTopResponse,
    CategoryValueTop,
)
from app.use_case.analyze._lemma_aggregate import (
    aggregate_categories,
    aggregate_dimension_lemmas,
    aggregate_vectors,
)


async def execute(
    db: AsyncSession,
    category_name: str,
    *,
    lang: LemmaLang = LemmaLang.ru,
    top_n: int = 10,
    top_n_lemmas: int = 10,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> CategoryTopResponse:
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

    posts = list((await db.execute(q)).scalars().all())
    texts = [p.text or "" for p in posts]
    non_empty = [t for t in texts if t.strip()]

    scores_list = await score_texts_batch_explained(non_empty, lang)
    vectors = [s for s, _dl, _c in scores_list]
    dim_lemmas = aggregate_dimension_lemmas([dl for _s, dl, _c in scores_list], top_n=top_n_lemmas)
    cat_shares = aggregate_categories([c for _s, _dl, c in scores_list])
    aggregate = aggregate_vectors(vectors)

    top_values = sorted(
        (
            CategoryValueTop(
                name=col,
                score=aggregate[col],
                lemmas=dim_lemmas.get(col, []) if aggregate[col] > 0 else [],
            )
            for col in CSV_COLUMNS
        ),
        key=lambda v: -v.score,
    )

    return CategoryTopResponse(
        category_name=category_name,
        lang=lang,
        posts_total=len(posts),
        posts_analyzed=len(vectors),
        posts_skipped_empty=len(texts) - len(non_empty),
        top_categories=[
            CategoryShareItem(category=k, share=v) for k, v in list(cat_shares.items())[:top_n]
        ],
        top_values=top_values[:top_n],
    )
