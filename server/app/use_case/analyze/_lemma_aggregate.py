"""Общая логика агрегации векторов ЦКМ (среднее + нормировка)."""
from __future__ import annotations

from app.application.services.content.lemma_scorer import CSV_COLUMNS


def aggregate_vectors(vectors: list[dict[str, float]]) -> dict[str, float]:
    """
    Среднее по каждому измерению, затем нормировка сумма → 1.0.
    При пустом списке возвращает нули.
    """
    if not vectors:
        return {k: 0.0 for k in CSV_COLUMNS}

    n = len(vectors)
    raw = {k: sum(v[k] for v in vectors) / n for k in CSV_COLUMNS}
    total = sum(raw.values())
    if total > 0:
        return {k: round(v / total, 4) for k, v in raw.items()}
    return {k: 0.0 for k in CSV_COLUMNS}
