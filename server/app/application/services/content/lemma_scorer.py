"""
Lemma-based Schwartz scoring from lemma_coefficients_*.csv.
"""
from __future__ import annotations

import asyncio
import csv
import json
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
    ru_un = "ru_un"
    ru_merged = "ru_merged"
    usa = "usa"
    usa_un = "usa_un"
    usa_merged = "usa_merged"
    frg = "frg"


_CSV_FILENAMES: dict[LemmaLang, str] = {
    LemmaLang.ru: "ru.csv",
    LemmaLang.ru_un: "ru_un.csv",
    LemmaLang.usa: "usa.csv",
    LemmaLang.usa_un: "usa_un.csv",
    LemmaLang.frg: "frg.csv",
}

# Merged langs combine two base dictionaries; duplicate lemmas get averaged weights.
_MERGED_COMPONENTS: dict[LemmaLang, tuple[LemmaLang, LemmaLang]] = {
    LemmaLang.ru_merged: (LemmaLang.ru, LemmaLang.ru_un),
    LemmaLang.usa_merged: (LemmaLang.usa, LemmaLang.usa_un),
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
    raise FileNotFoundError(f"{filename} not found")


def _clean_lemma(raw: str) -> str:
    s = re.sub(r"^1t", "", raw.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


LemmaScoreResult = tuple[dict[str, float], list[str], dict[str, float]]

# Internal index type: (single_dict, phrase_dict, phrase_pattern, categories_dict)
_Index = tuple[dict, dict, object, dict]


def _detect_encoding(path: Path) -> str:
    """Try UTF-8 first (incl. BOM), fall back to cp1251."""
    for enc in ("utf-8-sig", "utf-8", "cp1251"):
        try:
            with open(path, encoding=enc, newline="") as fh:
                fh.read()
            return enc
        except UnicodeDecodeError:
            continue
    return "cp1251"


def _build_phrase_pattern(phrase_dict: dict) -> object:
    if not phrase_dict:
        return None
    phrases_sorted = sorted(phrase_dict.keys(), key=len, reverse=True)
    return re.compile(r"\b(?:" + "|".join(re.escape(p) for p in phrases_sorted) + r")\b")


def _merge_indexes(idx_a: _Index, idx_b: _Index) -> _Index:
    """Combine two indexes. Duplicate lemmas get averaged weights."""
    single_a, phrase_a, _, cats_a = idx_a
    single_b, phrase_b, _, cats_b = idx_b

    def _merge_dicts(d_a: dict, d_b: dict) -> dict:
        merged: dict[str, dict[str, float]] = dict(d_a)
        for lemma, weights_b in d_b.items():
            if lemma in merged:
                weights_a = merged[lemma]
                merged[lemma] = {
                    k: (weights_a.get(k, 0.0) + weights_b.get(k, 0.0)) / 2
                    for k in CSV_COLUMNS
                }
            else:
                merged[lemma] = weights_b
        return merged

    merged_single = _merge_dicts(single_a, single_b)
    merged_phrase = _merge_dicts(phrase_a, phrase_b)
    # For categories, prefer dict_a; add any lemmas only in dict_b
    merged_cats = {**cats_b, **cats_a}

    return merged_single, merged_phrase, _build_phrase_pattern(merged_phrase), merged_cats


@lru_cache(maxsize=16)
def _load_index(lang: LemmaLang) -> _Index:
    # Merged langs: combine two base indexes
    if lang in _MERGED_COMPONENTS:
        lang_a, lang_b = _MERGED_COMPONENTS[lang]
        idx_a = _load_index(lang_a)
        idx_b = _load_index(lang_b)
        merged = _merge_indexes(idx_a, idx_b)
        single, phrase, _, _ = merged
        logger.info(
            "lemma_index_merged",
            lang=lang.value,
            components=[lang_a.value, lang_b.value],
            single=len(single),
            phrases=len(phrase),
        )
        return merged

    # Base langs: load from CSV
    try:
        path = _find_csv(lang)
    except FileNotFoundError as exc:
        logger.error("lemma_csv_not_found", lang=lang.value, error=str(exc))
        return {}, {}, None, {}

    single_dict: dict[str, dict[str, float]] = {}
    phrase_dict: dict[str, dict[str, float]] = {}
    categories_dict: dict[str, list[str]] = {}

    encoding = _detect_encoding(path)
    try:
        with open(path, encoding=encoding, newline="") as fh:
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
                # Columns 11+ are category data; join non-empty parts to support
                # files where the category field spans multiple columns (e.g. frg.csv).
                cat_parts = [row[i].strip() for i in range(11, len(row)) if row[i].strip()]
                raw_cat = " / ".join(cat_parts)
                cats = [c.strip().casefold() for c in raw_cat.split("/") if c.strip()] if raw_cat else []
                categories_dict[lemma] = cats
                if " " in lemma:
                    phrase_dict[lemma] = weights
                else:
                    single_dict[lemma] = weights

        phrase_pattern = _build_phrase_pattern(phrase_dict)
        logger.info("lemma_index_built", lang=lang.value, single=len(single_dict), phrases=len(phrase_dict))
        return single_dict, phrase_dict, phrase_pattern, categories_dict
    except Exception as exc:
        logger.error("lemma_table_load_failed", lang=lang.value, error=str(exc))
        return {}, {}, None, {}


def score_text(text: str, lang: LemmaLang = LemmaLang.ru) -> LemmaScoreResult:
    zero = {k: 0.0 for k in CSV_COLUMNS}
    empty: LemmaScoreResult = (zero, [], {})
    if not text or not text.strip():
        return empty
    single_dict, phrase_dict, phrase_pattern, categories_dict = _load_index(lang)
    if not single_dict and not phrase_dict:
        return empty
    text_lower = text.lower()
    totals: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    matched: list[str] = []
    cat_counts: dict[str, int] = {}

    def _add(lemma: str, weights: dict[str, float]) -> None:
        matched.append(lemma)
        for col in CSV_COLUMNS:
            totals[col] += weights.get(col, 0.0)
        for cat in categories_dict.get(lemma, []):
            cat_counts[cat] = cat_counts.get(cat, 0) + 1

    word_set = set(re.findall(r"\w+", text_lower))
    for word in word_set:
        w = single_dict.get(word)
        if w:
            _add(word, w)

    if phrase_pattern:
        seen: set[str] = set()
        for m in phrase_pattern.finditer(text_lower):
            phrase = m.group(0)
            if phrase in seen:
                continue
            seen.add(phrase)
            w = phrase_dict.get(phrase)
            if w:
                _add(phrase, w)

    if not matched:
        return empty

    s = sum(totals.values())
    if s > 0:
        totals = {k: round(v / s, 4) for k, v in totals.items()}

    ct = sum(cat_counts.values())
    cat_freq: dict[str, float] = {}
    if ct > 0:
        cat_freq = {k: round(v / ct, 4) for k, v in sorted(cat_counts.items(), key=lambda x: -x[1])}

    return totals, matched, cat_freq


_BASELINE_DIRS: tuple[Path, ...] = (
    Path("/app/server/lemma/lemma_baseline.json"),
    Path(__file__).parents[5] / "server" / "lemma" / "lemma_baseline.json",
    Path("server/lemma/lemma_baseline.json"),
)


@lru_cache(maxsize=1)
def _load_baseline_json() -> dict:
    for p in _BASELINE_DIRS:
        if p.exists():
            with open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("lemma_baseline.json not found")


def read_baseline(lang: LemmaLang) -> dict | None:
    try:
        return _load_baseline_json().get(lang.value)
    except Exception as exc:
        logger.error("lemma_baseline_read_failed", lang=lang.value, error=str(exc))
        return None


async def score_texts_batch(texts: list[str], lang: LemmaLang = LemmaLang.ru) -> list[LemmaScoreResult]:
    loop = asyncio.get_running_loop()
    return list(await asyncio.gather(*[loop.run_in_executor(None, score_text, text, lang) for text in texts]))
