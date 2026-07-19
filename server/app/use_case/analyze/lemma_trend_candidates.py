"""
GET /analyze/lemma/trend-candidates — "эмпирические" леммы: частотный поиск
кандидатных лемм по трендовым постам за последние N недель (по умолчанию 4).

Идея: для каждой из последних `weeks` недель берём трендовые кластеры этой
недели (через retrospective-режим list_trending_combined — как ретроспектива
в /clusters/trending, но окно шириной 7 суток на каждую неделю), считаем
частоту слов по всем постам этих кластеров за неделю, оставляем top_n_per_week
самых частых на каждую неделю (см. lemma_frequency.top_frequent_lemmas — та же
функция, что и для new_lemmas в /clusters/trending). Лемма-кандидат
возвращается, если она попала в top_n_per_week минимум в min_weeks_match (по
умолчанию 3) из этих недель — устойчиво повторяющаяся тема, а не разовый
всплеск.

Только частотный подсчёт — LLM здесь НЕ вызывается (в отличие от предыдущей
версии), поэтому метод быстрый и не рискует упереться в proxy-таймаут. Веса и
категорию для КОНКРЕТНОЙ леммы из этого списка нужно запросить отдельно —
lazy-load через use_case/analyze/lemma_trend_weight.py (GET
/lemma/trend-candidates/{lemma}/weights), по одному вызову LLM на лемму, только
для тех лемм, что реально интересны пользователю.

Леммы из чёрного списка (см. lemma_scorer.is_blacklisted / /lemma/blacklist)
исключаются из подсчёта частот целиком — не участвуют ни в одной неделе.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_frequency import top_frequent_lemmas
from app.application.services.content.lemma_scorer import LemmaLang, existing_lemmas
from app.infrastructure.repositories import list_posts_in_clusters, list_trending_combined
from app.presentation.schemas.analysis import (
    LemmaTrendCandidateItem,
    LemmaTrendCandidatesResponse,
    LemmaTrendWeekRange,
)
from app.utils.date_range import utc_window


async def execute(
    db: AsyncSession,
    *,
    lang: LemmaLang,
    source_ids: list[int] | None = None,
    category_names: list[str] | None = None,
    weeks: int = 4,
    min_weeks_match: int = 3,
    top_n_per_week: int = 30,
    min_posts: int = 3,
    trending_limit: int = 20,
    end_date: date | None = None,
) -> LemmaTrendCandidatesResponse:
    source_ids = source_ids or []
    category_names = category_names or []
    end = end_date or datetime.now(tz=timezone.utc).date()

    week_ranges: list[LemmaTrendWeekRange] = []
    week_top_words: list[list[tuple[str, int]]] = []

    for i in range(weeks):
        # Неделя i=0 — самая свежая: [end - (i+1)*7д; end - i*7д).
        week_end_date = end - timedelta(days=i * 7)
        week_start_date = end - timedelta(days=(i + 1) * 7)
        window_start, window_end = utc_window(week_start_date, 7)

        rows = await list_trending_combined(
            db,
            source_ids=source_ids or None,
            category_names=category_names or None,
            window_hours=7 * 24,
            min_posts=min_posts,
            limit=trending_limit,
            now=window_end,
            use_published_at=True,
            require_active=False,
        )
        cluster_ids = [cluster.id for cluster, _pw, _sw in rows]
        posts = await list_posts_in_clusters(
            db, cluster_ids, date_from=window_start, date_to=window_end
        )
        texts = [p.text for p in posts if p.text]
        ranked = top_frequent_lemmas(texts, lang, top_n_per_week)

        week_ranges.append(
            LemmaTrendWeekRange(
                date_from=week_start_date, date_to=week_end_date, posts_count=len(posts)
            )
        )
        week_top_words.append(ranked)

    match_counts: Counter = Counter()
    total_occurrences: Counter = Counter()
    for ranked in week_top_words:
        for lemma, cnt in ranked:
            match_counts[lemma] += 1
            total_occurrences[lemma] += cnt

    known = existing_lemmas(lang)
    ordered_lemmas = [
        lemma
        for lemma, matched in sorted(
            match_counts.items(),
            key=lambda kv: (-kv[1], -total_occurrences[kv[0]], kv[0]),
        )
        if matched >= min_weeks_match
    ]

    candidates = [
        LemmaTrendCandidateItem(
            lemma=lemma,
            weeks_matched=match_counts[lemma],
            total_occurrences=total_occurrences[lemma],
            in_dictionary=lemma in known,
        )
        for lemma in ordered_lemmas
    ]

    return LemmaTrendCandidatesResponse(
        lang=lang,
        weeks=weeks,
        min_weeks_match=min_weeks_match,
        top_n_per_week=top_n_per_week,
        week_ranges=week_ranges,
        candidates=candidates,
    )
