"""
GET /analyze/lemma/trend-candidates — "эмпирические" леммы: частотный поиск
кандидатных лемм по трендовым постам за последние N недель (по умолчанию 4),
с весами по 10 направлениям ЦКМ, предложенными LLM.

Идея: для каждой из последних `weeks` недель берём трендовые кластеры этой
недели (через retrospective-режим list_trending_combined — как ретроспектива
в /clusters/trending, но окно шириной 7 суток на каждую неделю), считаем
частоту слов по всем постам этих кластеров за неделю, оставляем top_n_per_week
самых частых на каждую неделю (см. lemma_frequency.top_frequent_lemmas — та же
функция, что и для new_lemmas в /clusters/trending). Лемма-кандидат
возвращается, если она попала в top_n_per_week минимум в min_weeks_match (по
умолчанию 3) из этих недель — устойчиво повторяющаяся тема, а не разовый
всплеск.

В отличие от /lemma/extract, лемму здесь предлагает не LLM, а частотный метод —
LLM привлекается только на втором шаге, чтобы подобрать веса/категорию для
первых `limit_candidates` кандидатов (по убыванию weeks_matched/total_occurrences),
аналогично /lemma/extract (один вызов LLM на лемму). Результат — предпросмотр,
ничего не сохраняет; чтобы добавить лемму в CSV, передайте кандидата (после
ручной проверки весов) в /lemma/append.

Леммы из чёрного списка (см. lemma_scorer.is_blacklisted / /lemma/blacklist)
исключаются из подсчёта частот целиком — не участвуют ни в одной неделе.
"""
from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_frequency import top_frequent_lemmas
from app.application.services.content.lemma_llm_extractor import assign_weights_to_lemmas
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
    limit_candidates: int = 8,
    end_date: date | None = None,
    provider: str | None = None,
    model: str | None = None,
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

    to_weight = ordered_lemmas[:limit_candidates]
    weighted = await assign_weights_to_lemmas(to_weight, lang, provider=provider, model=model)
    weights_by_lemma = {item["lemma"]: item for item in weighted}

    candidates: list[LemmaTrendCandidateItem] = []
    for lemma in ordered_lemmas:
        assigned = weights_by_lemma.get(lemma)
        candidates.append(
            LemmaTrendCandidateItem(
                lemma=lemma,
                weeks_matched=match_counts[lemma],
                total_occurrences=total_occurrences[lemma],
                in_dictionary=lemma in known,
                weights=assigned["weights"] if assigned else {},
                category=assigned["category"] if assigned else "",
                weights_assigned=assigned is not None,
            )
        )

    return LemmaTrendCandidatesResponse(
        lang=lang,
        weeks=weeks,
        min_weeks_match=min_weeks_match,
        top_n_per_week=top_n_per_week,
        limit_candidates=limit_candidates,
        week_ranges=week_ranges,
        candidates=candidates,
    )
