"""
Lemma-based Schwartz scoring from lemma_coefficients_RUS.csv.

Алгоритм:
  1. Загрузить CSV (CP1251, разделитель ";") один раз при запуске.
  2. Для каждого поискового слова/фразы из CSV проверить вхождение в текст (lower()).
  3. Суммировать веса совпавших строк по каждому из 10 измерений.
  4. Нормировать: делить на максимальное значение среди всех измерений (max → 1.0).
  5. Вернуть dict[str, float] с теми же ключами, что в CSV.
"""
from __future__ import annotations

import csv
import re
from functools import lru_cache
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

# Измерения в порядке колонок CSV (после колонки "lemma")
CSV_COLUMNS: tuple[str, ...] = (
    "Безопасность",
    "Социальная интегрированность",
    "Амбиозность",
    "Индивидуальность",
    "Рациональность",
    "Красота",
    "Социальная справедливость",
    "Гражданственность / Общественный договор",
    "Процветание",
    "Свобода совести",
)

# Путь к CSV: в контейнере /app/lemma_coefficients_RUS.csv,
# при локальной разработке ищем рядом с корнем проекта.
_CANDIDATE_PATHS: tuple[Path, ...] = (
    Path("/app/lemma_coefficients_RUS.csv"),
    Path(__file__).parents[5] / "lemma_coefficients_RUS.csv",
    Path("lemma_coefficients_RUS.csv"),
)


def _find_csv() -> Path:
    for p in _CANDIDATE_PATHS:
        if p.exists():
            return p
    raise FileNotFoundError(
        f"lemma_coefficients_RUS.csv не найден. Проверьте пути: {_CANDIDATE_PATHS}"
    )


def _clean_lemma(raw: str) -> str:
    """Убрать артефакт '1t' в начале (артефакт кодировки при экспорте) и пробелы."""
    s = re.sub(r"^1t", "", raw.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


@lru_cache(maxsize=1)
def _load_table() -> tuple[tuple[str, dict[str, float]], ...]:
    """Загружает таблицу из CSV один раз и кэширует. Возвращает tuple для хэшируемости."""
    path = _find_csv()
    entries: list[tuple[str, dict[str, float]]] = []
    try:
        with open(path, encoding="cp1251", newline="") as fh:
            reader = csv.reader(fh, delimiter=";")
            next(reader, None)  # пропустить заголовок
            for row in reader:
                if len(row) < len(CSV_COLUMNS) + 1:
                    continue
                lemma = _clean_lemma(row[0])
                if not lemma:
                    continue
                weights: dict[str, float] = {}
                for i, col in enumerate(CSV_COLUMNS, start=1):
                    try:
                        weights[col] = float(row[i].replace(",", ".").strip())
                    except (ValueError, IndexError):
                        weights[col] = 0.0
                # Пропускаем строки, где все веса нулевые
                if any(v > 0 for v in weights.values()):
                    entries.append((lemma, weights))
        logger.info("lemma_table_loaded", path=str(path), count=len(entries))
    except Exception as exc:
        logger.error("lemma_table_load_failed", error=str(exc))
    return tuple(entries)


def score_text(text: str) -> tuple[dict[str, float], list[str]]:
    """
    Подсчитывает нормированные значения 10 измерений для текста.

    Returns:
        (scores, matched_lemmas)
        scores — dict[str, float] с ключами из CSV_COLUMNS, значения 0.0–1.0.
        matched_lemmas — список найденных лемм (для отладки).
    """
    zero = {k: 0.0 for k in CSV_COLUMNS}
    if not text or not text.strip():
        return zero, []

    text_lower = text.lower()
    totals: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    matched: list[str] = []

    for lemma, weights in _load_table():
        # \b — граница слова (работает с кириллицей через Unicode \w в Python re)
        if re.search(r"\b" + re.escape(lemma) + r"\b", text_lower):
            matched.append(lemma)
            for col in CSV_COLUMNS:
                totals[col] += weights[col]

    if not matched:
        return zero, []

    # Нормировка: max → 1.0
    max_val = max(totals.values())
    if max_val > 0:
        totals = {k: round(v / max_val, 4) for k, v in totals.items()}

    return totals, matched
