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
    "\u0411\u0435\u0437\u043e\u043f\u0430\u0441\u043d\u043e\u0441\u0442\u044c",
    "\u0421\u043e\u0446\u0438\u0430\u043b\u044c\u043d\u0430\u044f \u0438\u043d\u0442\u0435\u0433\u0440\u0438\u0440\u043e\u0432\u0430\u043d\u043d\u043e\u0441\u0442\u044c",
    "\u0410\u043c\u0431\u0438\u043e\u0437\u043d\u043e\u0441\u0442\u044c",
    "\u0418\u043d\u0434\u0438\u0432\u0438\u0434\u0443\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u044c",
    "\u0420\u0430\u0446\u0438\u043e\u043d\u0430\u043b\u044c\u043d\u043e\u0441\u0442\u044c",
    "\u041a\u0440\u0430\u0441\u043e\u0442\u0430",
    "\u0421\u043e\u0446\u0438\u0430\u043b\u044c\u043d\u0430\u044f \u0441\u043f\u0440\u0430\u0432\u0435\u0434\u043b\u0438\u0432\u043e\u0441\u0442\u044c",
    "\u0413\u0440\u0430\u0436\u0434\u0430\u043d\u0441\u0442\u0432\u0435\u043d\u043d\u043e\u0441\u0442\u044c / \u041e\u0431\u0449\u0435\u0441\u0442\u0432\u0435\u043d\u043d\u044b\u0439 \u0434\u043e\u0433\u043e\u0432\u043e\u0440",
    "\u041f\u0440\u043e\u0446\u0432\u0435\u0442\u0430\u043d\u0438\u0435",
    "\u0421\u0432\u043e\u0431\u043e\u0434\u0430 \u0441\u043e\u0432\u0435\u0441\u0442\u0438",
)


class LemmaLang(str, Enum):
    ru = "ru"
    eng = "eng"
    de = "de"


_CSV_FILENAMES = {
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
    raise FileNotFoundError(f"{filename} not found")


def _clean_lemma(raw: str) -> str:
    s = re.sub(r"^1t", "", raw.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


LemmaScoreResult = tuple[dict[str, float], list[str], dict[str, float]]


@lru_cache(maxsize=8)
def _load_index(lang: LemmaLang):
    try:
        path = _find_csv(lang)
    except FileNotFoundError as exc:
        logger.error("lemma_csv_not_found", lang=lang.value, error=str(exc))
        return {}, {}, None, {}

    single_dict: dict[str, dict[str, float]] = {}
    phrase_dict: dict[str, dict[str, float]] = {}
    categories_dict: dict[str, list[str]] = {}

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
                raw_cat = row[11].strip() if len(row) > 11 else ""
                cats = [c.strip() for c in raw_cat.split("/") if c.strip()] if raw_cat else []
                categories_dict[lemma] = cats
                if " " in lemma:
                    phrase_dict[lemma] = weights
                else:
                    single_dict[lemma] = weights

        phrase_pattern = None
        if phrase_dict:
            phrases_sorted = sorted(phrase_dict.keys(), key=len, reverse=True)
            phrase_pattern = re.compile(
                r"\b(?:" + "|".join(re.escape(p) for p in phrases_sorted) + r")\b"
            )
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
