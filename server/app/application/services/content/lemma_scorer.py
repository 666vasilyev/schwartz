"""
Lemma-based Schwartz scoring from lemma_coefficients_*.csv.

Поддерживаемые языки: ru, eng, de.
Алгоритм:
  1. Загрузить CSV (CP1251, разделитель ";") один раз при запуске (кэш per-lang).
  2. Для каждой строки CSV проверить вхождение леммы в текст по границам слов (\b).
  3. Суммировать веса совпавших строк по каждому из 10 измерений.
  4. Нормировать: сумма всех значений → 1.0.
  5. Вернуть dict[str, float] с теми же ключами, что в CSV.
"""
from __future__ import annotations

import csv
import re
from enum import Enum
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


class LemmaLang(str, Enum):
    ru = "ru"
    eng = "eng"
    de = "de"


_CSV_FILENAMES: dict[LemmaLang, str] = {
    LemmaLang.ru: "lemma_coefficients_RUS.csv",
    LemmaLang.eng: "lemma_coefficients_ENG.csv",
    LemmaLang.de: "lemma_coefficients_DE.csv",
}

# Кандидаты директорий, где лежат CSV-файлы
_LEMMA_DIRS: tuple[Path, ...] = (
    Path("/app/server/lemma"),
    Path(__file__).parents[5] / "server" / "lemma",
    Path("server/lemma"),
    Path("lemma"),
)


def _find_csv(lang: LemmaLang) -> Path:
    filename = _CSV_FILENAMES[lang]
    for d in _LEMMA_DIRS:
        p = d / filename
        if p.exists():
            return p
    raise FileNotFoundError(
        f"{filename} не найден. Проверьте директории: {[str(d) for d in _LEMMA_DIRS]}"
    )


def _clean_lemma(raw: str) -> str:
    """Убрать артефакт '1t' в начале и лишние пробелы."""
    s = re.sub(r"^1t", "", raw.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


@lru_cache(maxsize=8)
def _load_table(lang: LemmaLang) -> tuple[tuple[str, dict[str, float]], ...]:
    """Загружает таблицу из CSV один раз и кэширует per-lang."""
    try:
        path = _find_csv(lang)
    except FileNotFoundError as exc:
        logger.error("lemma_csv_not_found", lang=lang.value, error=str(exc))
        return ()

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
                if any(v > 0 for v in weights.values()):
                    entries.append((lemma, weights))
        logger.info("lemma_table_loaded", lang=lang.value, path=str(path), count=len(entries))
    except Exception as exc:
        logger.error("lemma_table_load_failed", lang=lang.value, error=str(exc))
    return tuple(entries)


def score_text(
    text: str,
    lang: LemmaLang = LemmaLang.ru,
) -> tuple[dict[str, float], list[str]]:
    """
    Подсчитывает нормированные значения 10 измерений для текста.

    Returns:
        (scores, matched_lemmas)
        scores — dict[str, float] с ключами из CSV_COLUMNS, значения 0.0–1.0 (сумма = 1.0).
        matched_lemmas — список найденных лемм (для отладки).
    """
    zero = {k: 0.0 for k in CSV_COLUMNS}
    if not text or not text.strip():
        return zero, []

    table = _load_table(lang)
    if not table:
        return zero, []

    text_lower = text.lower()
    totals: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    matched: list[str] = []

    for lemma, weights in table:
        # \b — граница слова (работает с кириллицей через Unicode \w в Python re)
        if re.search(r"\b" + re.escape(lemma) + r"\b", text_lower):
            matched.append(lemma)
            for col in CSV_COLUMNS:
                totals[col] += weights[col]

    if not matched:
        return zero, []

    # Нормировка: сумма → 1.0
    total_sum = sum(totals.values())
    if total_sum > 0:
        totals = {k: round(v / total_sum, 4) for k, v in totals.items()}

    return totals, matched
