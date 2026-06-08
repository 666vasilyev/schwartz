"""POST /analyze/text/lemma — оценка ценностей по словарю lemma_coefficients_RUS.csv."""
from __future__ import annotations

from app.application.services.content.lemma_scorer import LemmaLang, score_text
from app.presentation.schemas.analysis import LemmaAnalysisResult


def execute(text: str, lang: LemmaLang = LemmaLang.ru) -> LemmaAnalysisResult:
    scores, matched, cat_freq = score_text(text, lang)
    return LemmaAnalysisResult(
        schwartz_values=scores,
        category_frequencies=cat_freq,
        matched_count=len(matched),
        matched_lemmas=matched,
    )
