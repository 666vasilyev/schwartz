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
