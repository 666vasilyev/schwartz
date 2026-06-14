"""POST /analyze/lemma/categories/granularity/{granularity} — временны́е ряды ЦКМ по нескольким категориям."""
from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime as dt

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import CSV_COLUMNS, LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post, source_category_link
from app.presentation.schemas.analysis import CategoriesSchwartzTimeseriesResponse
from app.use_case.analyze._lemma_aggregate import aggregate_vectors
from app.use_case.analyze._time_utils import TimeGranularity, period_range, period_start


async def execute(
    db: AsyncSession,
    categories: list[tuple[str, LemmaLang]],
    *,
    date_from: date,
    date_to: date,
    granularity: TimeGranularity = TimeGranularity.day,
) -> CategoriesSchwartzTimeseriesResponse:
    """
    categories — список пар (category_name, lang).

    Возвращает:
      granularity  — строка "day" / "week" / "month"
      periods      — список начал периодов по возрастанию
      posts_count  — {категория: [кол-во постов за каждый период]}
      data         — {параметр_шварца: {категория: [значение за каждый период]}}
    """
    category_names = [name for name, _ in categories]
    lang_by_cat: dict[str, LemmaLang] = {name: lang for name, lang in categories}
    zero_schwartz = {k: 0.0 for k in CSV_COLUMNS}

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

    # posts_by[(cat_name, period_start)] = [Post, ...]  (только непустые тексты)
    posts_by: dict[tuple[str, date], list[Post]] = defaultdict(list)
    for post, cat_name in rows:
        if post.published_at is not None and post.text and post.text.strip():
            key = (cat_name, period_start(post.published_at.date(), granularity))
            posts_by[key].append(post)

    all_periods = period_range(date_from, date_to, granularity)
    n = len(all_periods)

    # Инициализируем выходные структуры
    posts_count: dict[str, list[int]] = {cat: [0] * n for cat in category_names}
    # data[schwartz_param][cat_name] = [float * n]
    data: dict[str, dict[str, list[float]]] = {
        param: {cat: [0.0] * n for cat in category_names}
        for param in CSV_COLUMNS
    }

    for i, p in enumerate(all_periods):
        for cat_name in category_names:
            lang = lang_by_cat[cat_name]
            period_posts = posts_by.get((cat_name, p), [])

            if not period_posts:
                # нули уже проставлены при инициализации
                continue

            texts = [post.text or "" for post in period_posts]
            scores_list = await score_texts_batch(texts, lang)
            vectors = [s for s, _, _ in scores_list]
            schwartz = aggregate_vectors(vectors) if vectors else zero_schwartz

            posts_count[cat_name][i] = len(vectors)
            for param in CSV_COLUMNS:
                data[param][cat_name][i] = schwartz.get(param, 0.0)

    return CategoriesSchwartzTimeseriesResponse(
        granularity=granularity.value,
        periods=all_periods,
        posts_count=posts_count,
        data=data,
    )
