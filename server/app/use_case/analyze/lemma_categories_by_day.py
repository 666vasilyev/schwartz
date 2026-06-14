"""POST /analyze/lemma/categories/by_day — временны́е ряды ЦКМ по нескольким категориям."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import CSV_COLUMNS, LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post, source_category_link
from app.presentation.schemas.analysis import CategorySeriesDayItem, CategorySeriesResponse
from app.use_case.analyze._lemma_aggregate import aggregate_vectors


def _date_range(start: date, end: date) -> list[date]:
    days: list[date] = []
    cur = start
    while cur <= end:
        days.append(cur)
        cur += timedelta(days=1)
    return days


async def execute(
    db: AsyncSession,
    categories: list[tuple[str, LemmaLang]],
    *,
    date_from: date,
    date_to: date,
) -> list[CategorySeriesResponse]:
    """
    categories — список пар (category_name, lang).
    Возвращает временно́й ряд ЦКМ для каждой категории за диапазон [date_from, date_to].
    Дни без постов заполняются нулями.
    """
    category_names = [name for name, _ in categories]
    lang_by_cat: dict[str, LemmaLang] = {name: lang for name, lang in categories}
    zero_schwartz = {k: 0.0 for k in CSV_COLUMNS}

    from datetime import datetime as dt
    date_from_dt = dt.combine(date_from, dt.min.time())
    date_to_dt = dt.combine(date_to, dt.max.time())

    q = (
        select(Post, source_category_link.c.category_name)
        .join(source_category_link, Post.source_id == source_category_link.c.source_id)
        .where(source_category_link.c.category_name.in_(category_names))
        .where(Post.published_at >= date_from_dt)
        .where(Post.published_at <= date_to_dt)
        .order_by(source_category_link.c.category_name, Post.published_at)
    )

    rows = (await db.execute(q)).all()

    # posts_by_cat_day[(cat_name, day)] = [Post, ...]
    posts_by_cat_day: dict[tuple[str, date], list[Post]] = defaultdict(list)
    for post, cat_name in rows:
        if post.published_at is not None and post.text and post.text.strip():
            posts_by_cat_day[(cat_name, post.published_at.date())].append(post)

    all_days = _date_range(date_from, date_to)

    results: list[CategorySeriesResponse] = []
    for cat_name in category_names:
        lang = lang_by_cat[cat_name]
        days: list[CategorySeriesDayItem] = []

        for day in all_days:
            day_posts = posts_by_cat_day.get((cat_name, day), [])
            if not day_posts:
                days.append(CategorySeriesDayItem(date=day, posts_count=0, schwartz=dict(zero_schwartz)))
                continue

            texts = [p.text or "" for p in day_posts]
            scores_list = await score_texts_batch(texts, lang)
            vectors = [s for s, _, _ in scores_list]

            days.append(
                CategorySeriesDayItem(
                    date=day,
                    posts_count=len(vectors),
                    schwartz=aggregate_vectors(vectors),
                )
            )

        results.append(CategorySeriesResponse(category_name=cat_name, lang=lang.value, days=days))

    return results
