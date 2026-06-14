"""GET /analyze/lemma/category/{category_name}/by_day — ЦКМ категории в разбивке по периодам."""
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
from app.use_case.analyze._time_utils import TimeGranularity, period_range, period_start


async def execute(
    db: AsyncSession,
    category_name: str,
    *,
    lang: LemmaLang = LemmaLang.ru,
    granularity: TimeGranularity = TimeGranularity.day,
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

    posts = list((await db.execute(q)).scalars().all())

    # Группируем по началу периода (только посты с датой)
    posts_by_period: dict[date, list[Post]] = defaultdict(list)
    for post in posts:
        if post.published_at is not None:
            key = period_start(post.published_at.date(), granularity)
            posts_by_period[key].append(post)

    # Если задан диапазон — заполняем пустые периоды нулями; иначе — только периоды с постами
    if date_from is not None and date_to is not None:
        all_periods = period_range(date_from.date(), date_to.date(), granularity)
    else:
        all_periods = sorted(posts_by_period.keys(), reverse=True)

    zero_schwartz = {k: 0.0 for k in (aggregate_vectors([]))}

    items: list[CategoryLemmaDayItem] = []
    for p in (all_periods if (date_from is None) else reversed(list(all_periods))):
        period_posts = posts_by_period.get(p, [])
        texts = [post.text or "" for post in period_posts]
        non_empty = [t for t in texts if t.strip()]
        skipped = len(texts) - len(non_empty)

        if not non_empty:
            items.append(CategoryLemmaDayItem(
                period_start=p,
                posts_total=len(period_posts),
                posts_analyzed=0,
                posts_skipped_empty=skipped,
                aggregate_schwartz=dict(zero_schwartz),
                aggregate_categories={},
            ))
            continue

        scores_list = await score_texts_batch(non_empty, lang)
        vectors = [s for s, _, _c in scores_list]
        cat_freqs = [c for _s, _, c in scores_list]

        items.append(CategoryLemmaDayItem(
            period_start=p,
            posts_total=len(period_posts),
            posts_analyzed=len(vectors),
            posts_skipped_empty=skipped,
            aggregate_schwartz=aggregate_vectors(vectors),
            aggregate_categories=aggregate_categories(cat_freqs),
        ))

    # Без явного диапазона — сортируем по убыванию
    if date_from is None:
        items.sort(key=lambda x: x.period_start, reverse=True)

    return CategoryLemmaByDayResponse(
        category_name=category_name,
        granularity=granularity.value,
        periods=items,
    )
