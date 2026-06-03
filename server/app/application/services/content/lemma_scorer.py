"""
Lemma-based Schwartz scoring from lemma_coefficients_*.csv.

Оптимизации:
  - Все леммы объединяются в одну скомпилированную regex при загрузке (один проход по тексту).
  - Таблица и pattern кешируются per-lang через lru_cache.
  - score_text — чистая sync-функция; для пакетного анализа используй score_texts_batch.
"""
from __future__ import annotations

import asyncio
import csv
import re
from enum import Enum
from functools import lru_cache
from pathlib import Path

from app.utils.logger import get_logger

logger = get_logger(__name__)

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
    s = re.sub(r"^1t", "", raw.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


# Индекс: (single_dict, phrase_dict, phrase_pattern)
#   single_dict:    {word -> weights}       — 95% лемм, O(1) hash lookup
#   phrase_dict:    {phrase -> weights}     — 5% лемм, regex
#   phrase_pattern: compiled regex из phrase_dict (короткая, ~89 альтернаций)
_Index = tuple[
    dict[str, dict[str, float]],  # single_dict
    dict[str, dict[str, float]],  # phrase_dict
    re.Pattern | None,             # phrase_pattern
]


@lru_cache(maxsize=8)
def _load_index(lang: LemmaLang) -> _Index:
    try:
        path = _find_csv(lang)
    except FileNotFoundError as exc:
        logger.error("lemma_csv_not_found", lang=lang.value, error=str(exc))
        return {}, {}, None

    single_dict: dict[str, dict[str, float]] = {}
    phrase_dict: dict[str, dict[str, float]] = {}

    try:
        with open(path, encoding="cp1251", newline="") as fh:
            reader = csv.reader(fh, delimiter=";")
            next(reader, None)
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
                if not any(v > 0 for v in weights.values()):
                    continue
                if " " in lemma:
                    phrase_dict[lemma] = weights
                else:
                    single_dict[lemma] = weights

        # Regex только для многословных фраз (~89 паттернов вместо 1895)
        phrase_pattern: re.Pattern | None = None
        if phrase_dict:
            phrases_sorted = sorted(phrase_dict.keys(), key=len, reverse=True)
            phrase_pattern = re.compile(
                r"\b(?:" + "|".join(re.escape(p) for p in phrases_sorted) + r")\b",
            )

        logger.info(
            "lemma_index_built",
            lang=lang.value,
            path=str(path),
            single=len(single_dict),
            phrases=len(phrase_dict),
        )
        return single_dict, phrase_dict, phrase_pattern

    except Exception as exc:
        logger.error("lemma_table_load_failed", lang=lang.value, error=str(exc))
        return {}, {}, None


def score_text(
    text: str,
    lang: LemmaLang = LemmaLang.ru,
) -> tuple[dict[str, float], list[str]]:
    """
    Двухуровневый поиск:
      - однословные леммы: токенизация текста → set → O(1) hash lookup
      - многословные фразы: короткая regex (~89 паттернов)

    Sync, CPU-bound — вызывай через score_texts_batch для пакетной обработки.
    """
    zero = {k: 0.0 for k in CSV_COLUMNS}
    if not text or not text.strip():
        return zero, []

    single_dict, phrase_dict, phrase_pattern = _load_index(lang)
    if not single_dict and not phrase_dict:
        return zero, []

    text_lower = text.lower()
    totals: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    matched: list[str] = []

    # 1. Однословные: токенизация → set intersection со словарём
    word_set = set(re.split(r"\W+", text_lower))
    for word in word_set:
        weights = single_dict.get(word)
        if weights:
            matched.append(word)
            for col in CSV_COLUMNS:
                totals[col] += weights.get(col, 0.0)

    # 2. Многословные фразы: короткая regex
    if phrase_pattern:
        seen_phrases: set[str] = set()
        for m in phrase_pattern.finditer(text_lower):
            phrase = m.group(0)
            if phrase in seen_phrases:
                continue
            seen_phrases.add(phrase)
            weights = phrase_dict.get(phrase)
            if weights:
                matched.append(phrase)
                for col in CSV_COLUMNS:
                    totals[col] += weights.get(col, 0.0)

    if not matched:
        return zero, []

    total_sum = sum(totals.values())
    if total_sum > 0:
        totals = {k: round(v / total_sum, 4) for k, v in totals.items()}

    return totals, matched


async def score_texts_batch(
    texts: list[str],
    lang: LemmaLang = LemmaLang.ru,
) -> list[tuple[dict[str, float], list[str]]]:
    """
    Параллельный анализ списка текстов через threadpool.
    Используй для пакетной обработки постов источника/категории.
    """
    loop = asyncio.get_running_loop()
    return list(
        await asyncio.gather(
            *[loop.run_in_executor(None, score_text, text, lang) for text in texts]
        )
    )
