"""
POST /analyze/lemma/categories/overview — объединённый ответ вместо пары
запросов GET /clusters/trending + POST /lemma/categories/combined за один и
тот же период: тренды (топики, new_lemmas) и комбинированная ЦКМ по тем же
категориям в одном вызове. Экономит round-trip'ы там, где фронту нужны оба
среза для одной и той же карточки "категория + день" — раньше это были два
отдельных запроса с одинаковыми фильтрами по категории/дате (и по одному
такому запросу лишний раз на каждую категорию, если их несколько).

categories — список пар (category_name, lang), как в lemma_categories_combined.
Для тренда язык не важен (он влияет только на new_lemmas каждого кластера —
считается отдельным lemma_lang), поэтому в тренды уходит только множество
уникальных имён категорий.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang
from app.infrastructure.repositories import list_trending_combined
from app.presentation.schemas.analysis import CategoriesOverviewResponse
from app.presentation.schemas.cluster import TrendingClustersResponse
from app.use_case.analyze import lemma_categories_combined as lemma_categories_combined_uc
from app.use_case.clusters._trending_common import build_trending_items


async def execute(
    db: AsyncSession,
    categories: list[tuple[str, LemmaLang]],
    *,
    date_from: datetime,
    date_to: datetime,
    trending_limit: int = 20,
    min_posts: int = 3,
    top_n_lemmas: int = 15,
    posts_limit: int | None = None,
    lemma_lang: LemmaLang = LemmaLang.ru,
    lemma_top_n: int = 10,
) -> CategoriesOverviewResponse:
    category_names = sorted({name for name, _lang in categories})

    # window_hours передаётся дробным (list_trending_combined просто кладёт его в
    # timedelta(hours=...), которой всё равно int или float) — так окно точно
    # совпадает с [date_from; date_to], а не округляется до целых часов.
    window_hours = (date_to - date_from).total_seconds() / 3600
    rows = await list_trending_combined(
        db,
        category_names=category_names or None,
        window_hours=window_hours,
        min_posts=min_posts,
        limit=trending_limit,
        now=date_to,
        use_published_at=True,
        require_active=False,
    )
    items = await build_trending_items(
        db, rows, window_start=date_from, window_end=date_to,
        lemma_lang=lemma_lang, lemma_top_n=lemma_top_n,
    )
    trending = TrendingClustersResponse(
        items=items,
        window_hours=round(window_hours),
        min_posts=min_posts,
        source_ids=[],
        category_names=category_names,
        as_of=date_from.date(),
    )

    ckm = await lemma_categories_combined_uc.execute(
        db, categories, top_n_lemmas=top_n_lemmas, limit=posts_limit,
        date_from=date_from, date_to=date_to,
    )

    return CategoriesOverviewResponse(
        date_from=date_from, date_to=date_to, trending=trending, ckm=ckm,
    )
