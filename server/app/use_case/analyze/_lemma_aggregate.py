"""Общая логика агрегации векторов ЦКМ (среднее + нормировка)."""
from __future__ import annotations

from app.application.services.content.lemma_scorer import CSV_COLUMNS


def aggregate_vectors(vectors: list[dict[str, float]]) -> dict[str, float]:
    """Среднее по Шварцу, нормировка сумма → 1.0."""
    if not vectors:
        return {k: 0.0 for k in CSV_COLUMNS}
    n = len(vectors)
    raw = {k: sum(v[k] for v in vectors) / n for k in CSV_COLUMNS}
    total = sum(raw.values())
    if total > 0:
        return {k: round(v / total, 4) for k, v in raw.items()}
    return {k: 0.0 for k in CSV_COLUMNS}


def aggregate_categories(cat_freq_list: list[dict[str, float]]) -> dict[str, float]:
    """Суммируем частоты категорий по всем постам, нормируем сумма → 1.0."""
    if not cat_freq_list:
        return {}
    totals: dict[str, float] = {}
    for cat_freq in cat_freq_list:
        for cat, freq in cat_freq.items():
            totals[cat] = totals.get(cat, 0.0) + freq
    total = sum(totals.values())
    if total > 0:
        return {
            k: round(v / total, 4)
            for k, v in sorted(totals.items(), key=lambda x: -x[1])
        }
    return {}


def aggregate_dimension_lemmas(
    dimension_lemmas_list: list[dict[str, list[str]]],
    *,
    top_n: int | None = None,
) -> dict[str, list[str]]:
    """
    Объединяет per-post разбивки "лемма → каким параметрам дала вес" (см.
    score_text_explained) в один результат на весь пул постов: для каждого
    параметра ЦКМ — список давших ему вес лемм, отсортированный по числу
    постов, где лемма сработала (по убыванию; при равенстве — по алфавиту, для
    детерминированности), опционально обрезанный до top_n.

    Считает частоту "в скольких постах лемма дала вес параметру", а не
    суммарную величину веса — это дешевле и не требует протаскивать вес каждой
    отдельной леммы через весь пайплайн ради, по сути, ранжирования.
    """
    if not dimension_lemmas_list:
        return {k: [] for k in CSV_COLUMNS}

    counts: dict[str, dict[str, int]] = {k: {} for k in CSV_COLUMNS}
    for dim_lemmas in dimension_lemmas_list:
        for col, lemmas in dim_lemmas.items():
            col_counts = counts.setdefault(col, {})
            for lemma in lemmas:
                col_counts[lemma] = col_counts.get(lemma, 0) + 1

    result: dict[str, list[str]] = {}
    for col, col_counts in counts.items():
        ranked = sorted(col_counts.items(), key=lambda item: (-item[1], item[0]))
        lemmas_ranked = [lemma for lemma, _count in ranked]
        result[col] = lemmas_ranked[:top_n] if top_n is not None else lemmas_ranked
    return result
