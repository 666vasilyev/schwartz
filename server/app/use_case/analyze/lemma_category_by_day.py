"""GET /analyze/lemma/category/{category_name}/by_day — ЦКМ категории по словарному методу, в разбивке по дням."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post, SourceCategoryModel, source_category_link
from app.presentation.schemas.analysis import CategoryLemmaByDayResponse, CategoryLemmaDayItem
from app.use_case.analyze._lemma_aggregate import aggregate_categories, aggregate_vectors


async def execute(
    db: AsyncSession,
    category_name: str,
    *,
    lang: LemmaLang = LemmaLang.ru,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> CategoryLemmaByDayResponse:
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

    # Группируем по дате публикации (посты без published_at в разбивку по дням не попадают)
    posts_by_day: dict[date, list[Post]] = defaultdict(list)
    for post in posts:
        if post.published_at is not None:
            posts_by_day[post.published_at.date()].append(post)

    days: list[CategoryLemmaDayItem] = []
    for day in sorted(posts_by_day.keys(), reverse=True):
        day_posts = posts_by_day[day]
        texts = [p.text or "" for p in day_posts]
        non_empty = [t for t in texts if t.strip()]
        skipped = len(texts) - len(non_empty)

        scores_list = await score_texts_batch(non_empty, lang)
        vectors = [s for s, _, _c in scores_list]
        cat_freqs = [c for _s, _, c in scores_list]

        days.append(
            CategoryLemmaDayItem(
                date=day,
                posts_total=len(day_posts),
                posts_analyzed=len(vectors),
                posts_skipped_empty=skipped,
                aggregate_schwartz=aggregate_vectors(vectors),
                aggregate_categories=aggregate_categories(cat_freqs),
            )
        )

    return CategoryLemmaByDayResponse(category_name=category_name, days=days)
