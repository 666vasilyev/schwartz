"""POST /analyze/text/lemma — оценка ценностей по словарю lemma_coefficients_RUS.csv."""
from __future__ import annotations

from app.application.services.content.lemma_scorer import CSV_COLUMNS, score_text
from app.presentation.schemas.analysis import LemmaAnalysisResult


def execute(text: str) -> LemmaAnalysisResult:
    scores, matched = score_text(text)
    return LemmaAnalysisResult(
        schwartz_values=scores,
        matched_count=len(matched),
        matched_lemmas=matched,
    )
