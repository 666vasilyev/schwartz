"""
GET /analyze/lemma/trend-candidates/{lemma}/weights — веса по 10 направлениям
ЦКМ и категория для ОДНОЙ конкретной леммы (lazy-load).

Пара к /analyze/lemma/trend-candidates: тот эндпоинт отдаёт только список лемм
с частотными метриками (без LLM — быстро). Здесь же по требованию, для одной
выбранной пользователем леммы, вызывается LLM (один вызов — см.
lemma_llm_extractor.assign_weights_to_lemmas) и возвращаются веса/категория,
которые можно передать в /lemma/append как есть.

Лемма не обязана быть из /lemma/trend-candidates — эндпоинт просто размечает
любое переданное слово/словосочетание тем же способом, каким размечались бы
кандидаты трендов.
"""
from __future__ import annotations

from app.application.services.content.lemma_llm_extractor import assign_weights_to_lemmas
from app.application.services.content.lemma_scorer import LemmaLang
from app.presentation.schemas.analysis import NewLemmaItem


async def execute(
    lemma: str,
    lang: LemmaLang,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> NewLemmaItem:
    results = await assign_weights_to_lemmas([lemma], lang, provider=provider, model=model)
    item = results[0]
    return NewLemmaItem(lemma=item["lemma"], weights=item["weights"], category=item["category"])
