"""Мелкие статистические помощники для калькуляторов."""
from __future__ import annotations

import math
from collections import Counter
from datetime import datetime
from typing import Any, Iterable

import numpy as np

WEEKDAYS = ["пн", "вт", "ср", "чт", "пт", "сб", "вс"]


def r4(x: float | None, nd: int = 4) -> float | None:
    return None if x is None else round(float(x), nd)


def share(part: int | float, total: int | float) -> float | None:
    return round(part / total, 4) if total else None


def top(counter: Counter, n: int = 20, key: str = "key") -> list[dict[str, Any]]:
    return [{key: k, "count": c} for k, c in counter.most_common(n)]


def pearson(x: list[float], y: list[float]) -> float | None:
    if len(x) < 5 or len(x) != len(y):
        return None
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    if a.std() == 0 or b.std() == 0:
        return None
    return r4(np.corrcoef(a, b)[0, 1])


def _ranks(v: list[float]) -> list[float]:
    arr = np.asarray(v, dtype=float)
    order = arr.argsort(kind="mergesort")
    ranks = np.empty(len(arr))
    i = 0
    while i < len(arr):
        j = i
        while j + 1 < len(arr) and arr[order[j + 1]] == arr[order[i]]:
            j += 1
        ranks[order[i : j + 1]] = (i + j) / 2 + 1
        i = j + 1
    return ranks.tolist()


def spearman(x: list[float], y: list[float]) -> float | None:
    if len(x) < 5 or len(x) != len(y):
        return None
    return pearson(_ranks(x), _ranks(y))


def gini(values: Iterable[float]) -> float | None:
    v = sorted(float(x) for x in values if x >= 0)
    n = len(v)
    s = sum(v)
    if n == 0 or s == 0:
        return None
    cum = sum((i + 1) * x for i, x in enumerate(v))
    return r4((2 * cum) / (n * s) - (n + 1) / n)


def mean(v: list[float]) -> float | None:
    return r4(sum(v) / len(v)) if v else None


def std(v: list[float]) -> float | None:
    return r4(float(np.std(v))) if len(v) > 1 else None


def day(dt: datetime) -> str:
    return dt.date().isoformat()


def week(dt: datetime) -> str:
    y, w, _ = dt.isocalendar()
    return f"{y}-W{w:02d}"


def month(dt: datetime) -> str:
    return f"{dt.year}-{dt.month:02d}"


def syllables(word: str) -> int:
    return max(1, sum(1 for ch in word.lower() if ch in "аеёиоуыэюяaeiouy"))


def numeric_diff(a: Any, b: Any) -> Any:
    """Рекурсивная разница значений метрики «после − до» (для сравнения периодов)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return None
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        d = {"before": a, "after": b, "delta": r4(b - a)}
        if a:
            d["delta_pct"] = r4((b - a) / abs(a) * 100, 2)
        return d
    if isinstance(a, dict) and isinstance(b, dict):
        out = {}
        for k in a.keys() & b.keys():
            sub = numeric_diff(a[k], b[k])
            if sub not in (None, {}, []):
                out[k] = sub
        return out
    return None


def is_nan(x: Any) -> bool:
    return isinstance(x, float) and math.isnan(x)
