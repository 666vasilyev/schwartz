"""
POST /analyze/lemma/weights — универсальный расчёт весов ЦКМ (через LLM) для
готового списка лемм, независимо от их источника (буфер выделений, кандидаты
из трендов, что угодно ещё, что отдаёт на вход просто список слов).

Замена точечной GET /lemma/trend-candidates/{lemma}/weights (deprecated, см.
routes/content.py) — та же логика (assign_weights_to_lemmas), но на список, а
не одну лемму. Для одной леммы — просто список из одного элемента.
"""
from __future__ import annotations

from app.application.services.content.lemma_llm_extractor import assign_weights_to_lemmas
from app.application.services.content.lemma_scorer import LemmaLang, clean_lemma
from app.presentation.schemas.analysis import LemmaWeightsResponse, NewLemmaItem

_MAX_LEMMAS = 50


async def execute(
    lemmas: list[str],
    lang: LemmaLang,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> LemmaWeightsResponse:
    # Нормализация + dedupe с сохранением порядка — леммы могут прийти из
    # разных мест (буфер, тренды, фронт вручную) не всегда в чистом виде.
    cleaned = list(dict.fromkeys(k for k in (clean_lemma(x) for x in lemmas) if k))
    cleaned = cleaned[:_MAX_LEMMAS]

    results: list[NewLemmaItem] = []
    failed: list[str] = []
    if cleaned:
        raw_results = await assign_weights_to_lemmas(cleaned, lang, provider=provider, model=model)
        for item in raw_results:
            if not item["category"]:
                # LLM не вернула разбираемый ответ (см. docstring assign_weights_to_lemmas)
                failed.append(item["lemma"])
                continue
            results.append(NewLemmaItem(lemma=item["lemma"], weights=item["weights"], category=item["category"]))

    return LemmaWeightsResponse(lang=lang, results=results, failed=failed)
