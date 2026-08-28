"""
GET /api/v1/analytics/lemma/counts — частотная статистика лемм (сколько лемм
словаря имеют ненулевой вес по каждому параметру ЦКМ) сразу по всем словарям
(ru, ru_un, ru_ch, ru_merged, usa, usa_un, usa_ch, usa_merged, frg) — отдельный экран
дашборда, не привязан к эталонным весам baseline (см. lemma_baseline.py).
"""
from __future__ import annotations

from app.application.services.content.lemma_scorer import LemmaLang, count_lemmas_by_parameter
from app.presentation.schemas.analysis import LemmaParameterCountsResponse
from app.presentation.schemas.analytics import LemmaCountsAllResponse


def execute() -> LemmaCountsAllResponse:
    items = [
        LemmaParameterCountsResponse(lang=lang, counts=count_lemmas_by_parameter(lang))
        for lang in LemmaLang
    ]
    return LemmaCountsAllResponse(dictionaries=items)
