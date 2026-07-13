"""
POST /analyze/lemma/categories/combined — ЦКМ по ОДНОМУ объединённому результату
для списка категорий (у каждой — свой язык словаря, словарный метод), с разбивкой
по леммам на каждый параметр.

В отличие от lemma_categories.py (тот же вход — список пар category_name+lang —
но список результатов, по одному на категорию), здесь всегда ровно один
результат на весь запрос: все получившиеся per-post векторы объединяются в
единый агрегат вместо того, чтобы возвращаться отдельно по категориям.
"""
from __future__ import annotations

from collections import defaultdict
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
    CategoryLangItem,
    CategoriesLemmaCkmResponse,
    LemmaDimensionScore,
)
from app.use_case.analyze._lemma_aggregate import (
    aggregate_dimension_lemmas,
    aggregate_vectors,
)


async def execute(
    db: AsyncSession,
    categories: list[tuple[str, LemmaLang]],
    *,
    top_n_lemmas: int = 15,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> CategoriesLemmaCkmResponse:
    """
    categories — список пар (category_name, lang), как в lemma_categories.py.
    Источник, входящий сразу в несколько запрошенных категорий, встретится в
    выборке один раз НА КАЖДУЮ такую категорию (посты оцениваются словарём
    каждой из них по отдельности) — это совпадает с поведением
    некомбинированного /lemma/categories; здесь просто всё мержится в один
    агрегат на последнем шаге, а не возвращается списком.
    """
    category_names = [name for name, _ in categories]
    lang_by_cat: dict[str, LemmaLang] = {name: lang for name, lang in categories}

    q = (
        select(Post, source_category_link.c.category_name)
        .join(source_category_link, Post.source_id == source_category_link.c.source_id)
        .where(source_category_link.c.category_name.in_(category_names))
        .order_by(
            source_category_link.c.category_name,
            Post.published_at.desc().nulls_last(),
            Post.id.desc(),
        )
    )
    if date_from is not None:
        q = q.where(Post.published_at >= date_from)
    if date_to is not None:
        q = q.where(Post.published_at <= date_to)

    result = await db.execute(q)
    rows = result.all()  # list of Row(Post, category_name)

    # Группируем по категории, применяем limit на каждую (как в lemma_categories.py)
    posts_by_cat: dict[str, list[Post]] = defaultdict(list)
    for row in rows:
        post, cat_name = row[0], row[1]
        if limit is None or len(posts_by_cat[cat_name]) < limit:
            posts_by_cat[cat_name].append(post)

    posts_total = 0
    all_vectors: list[dict[str, float]] = []
    all_dim_lemmas: list[dict[str, list[str]]] = []
    skipped_total = 0

    for cat_name in category_names:
        lang = lang_by_cat[cat_name]
        posts = posts_by_cat.get(cat_name, [])
        posts_total += len(posts)
        texts = [p.text or "" for p in posts]
        non_empty = [t for t in texts if t.strip()]
        skipped_total += len(texts) - len(non_empty)

        scores_list = await score_texts_batch_explained(non_empty, lang)
        all_vectors.extend(s for s, _dl, _c in scores_list)
        all_dim_lemmas.extend(dl for _s, dl, _c in scores_list)

    aggregate = aggregate_vectors(all_vectors)
    dim_lemmas = aggregate_dimension_lemmas(all_dim_lemmas, top_n=top_n_lemmas)

    values = {
        col: LemmaDimensionScore(score=aggregate[col], lemmas=dim_lemmas.get(col, []))
        for col in CSV_COLUMNS
    }

    return CategoriesLemmaCkmResponse(
        categories=[CategoryLangItem(category_name=name, lang=lang) for name, lang in categories],
        posts_total=posts_total,
        posts_analyzed=len(all_vectors),
        posts_skipped_empty=skipped_total,
        values=values,
    )
