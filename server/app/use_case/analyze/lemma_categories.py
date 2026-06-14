"""POST /analyze/lemma/categories — агрегат ЦКМ по списку категорий (словарный метод, один результат на категорию)."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang, score_texts_batch
from app.infrastructure.db.orm.models import Post, source_category_link
from app.presentation.schemas.analysis import SourceLemmaAnalysisResponse
from app.use_case.analyze._lemma_aggregate import aggregate_categories, aggregate_vectors


async def execute(
    db: AsyncSession,
    categories: list[tuple[str, LemmaLang]],
    *,
    limit: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> list[SourceLemmaAnalysisResponse]:
    """
    categories — список пар (category_name, lang). Каждая категория может иметь свой язык словаря.
    Один запрос достаёт посты для всех запрошенных категорий.
    Пост привязан к категории через: post.source_id → source_category_links.source_id → category_name.
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

    # Группируем по категории, применяем limit на каждую
    posts_by_cat: dict[str, list[Post]] = defaultdict(list)
    for row in rows:
        post, cat_name = row[0], row[1]
        if limit is None or len(posts_by_cat[cat_name]) < limit:
            posts_by_cat[cat_name].append(post)

    # Скоринг и сборка результатов в том же порядке, что входной список
    results: list[SourceLemmaAnalysisResponse] = []
    for cat_name in category_names:
        lang = lang_by_cat[cat_name]
        posts = posts_by_cat.get(cat_name, [])
        texts = [p.text or "" for p in posts]
        non_empty = [t for t in texts if t.strip()]
        skipped = len(texts) - len(non_empty)

        scores_list = await score_texts_batch(non_empty, lang)
        vectors = [s for s, _, _c in scores_list]
        cat_freqs = [c for _s, _, c in scores_list]

        results.append(SourceLemmaAnalysisResponse(
            source_id=None,
            category_name=cat_name,
            posts_total=len(posts),
            posts_analyzed=len(vectors),
            posts_skipped_empty=skipped,
            aggregate_schwartz=aggregate_vectors(vectors),
            aggregate_categories=aggregate_categories(cat_freqs),
        ))

    return results
