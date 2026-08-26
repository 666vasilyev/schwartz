"""
GET /api/v1/analytics/lemma/baseline — эталонные ЦКМ сразу по всем словарям
(ru, ru_un, ru_merged, usa, usa_un, usa_merged, frg) — одним запросом для
страницы Аналитика. Частотная статистика — отдельно, см. lemma_counts.py
(разные экраны дашборда).
"""
from __future__ import annotations

from app.application.services.content.lemma_scorer import LemmaLang, read_baseline
from app.presentation.schemas.analytics import LemmaBaselineAllResponse, LemmaBaselineItem


def execute() -> LemmaBaselineAllResponse:
    items: list[LemmaBaselineItem] = []
    for lang in LemmaLang:
        result = read_baseline(lang)
        if result is None:
            continue
        items.append(LemmaBaselineItem(**result, lang=lang))
    return LemmaBaselineAllResponse(dictionaries=items)
