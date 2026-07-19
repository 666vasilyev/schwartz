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


def _find_in_lemma_dirs(filename: str, *, create: bool = False) -> Path:
    """
    Ищет `filename` по очереди в _LEMMA_DIRS (первое совпадение побеждает) —
    общая логика для поиска CSV-словаря и файла чёрного списка (отличаются
    только именем файла и тем, нужно ли создавать его при отсутствии).

    create=True — если нигде не найден, создать пустой файл в первой
    существующей директории из _LEMMA_DIRS (нужно файлам, которых может не
    быть до первой записи, например ещё не созданный чёрный список).
    """
    for d in _LEMMA_DIRS:
        p = d / filename
        if p.exists():
            return p
    if not create:
        raise FileNotFoundError(f"{filename} not found")
    for d in _LEMMA_DIRS:
        if d.exists():
            p = d / filename
            p.write_text("", encoding="utf-8")
            return p
    raise FileNotFoundError(f"Не найдена ни одна из директорий словарей для создания {filename}")


def _find_csv(lang: LemmaLang) -> Path:
    return _find_in_lemma_dirs(_CSV_FILENAMES[lang])


def _clean_lemma(raw: str) -> str:
    s = re.sub(r"^1t", "", raw.strip(), flags=re.IGNORECASE)
    return s.strip().lower()


LemmaScoreResult = tuple[dict[str, float], list[str], dict[str, float]]
# (totals, dimension_lemmas, cat_freq) — как LemmaScoreResult, но matched заменён
# на разбивку "какие леммы дали вес каждому из 10 параметров ЦКМ".
LemmaScoreResultExplained = tuple[dict[str, float], dict[str, list[str]], dict[str, float]]

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


def list_lemmas(
    lang: LemmaLang,
    *,
    search: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """
    Текущее содержимое словаря `lang` (включая merged — они читаются как обычно,
    просто без права записи в append_lemmas). Для просмотра перед/после ручного
    редактирования CSV.

    search — подстрока для фильтра по лемме (регистронезависимо).
    Возвращает (страница_строк, всего_после_фильтра); строки отсортированы по лемме.
    """
    single_dict, phrase_dict, _, categories_dict = _load_index(lang)
    all_lemmas = sorted(set(single_dict) | set(phrase_dict))

    if search:
        needle = search.strip().casefold()
        all_lemmas = [lemma for lemma in all_lemmas if needle in lemma.casefold()]

    total = len(all_lemmas)
    page = all_lemmas[offset : offset + limit]

    rows: list[dict] = []
    for lemma in page:
        weights = single_dict.get(lemma) or phrase_dict.get(lemma) or {}
        category = " / ".join(categories_dict.get(lemma, []))
        rows.append({"lemma": lemma, "weights": dict(weights), "category": category})

    return rows, total


def _score_text_full(
    text: str, lang: LemmaLang
) -> tuple[dict[str, float], dict[str, list[str]], list[str], dict[str, float]]:
    """
    Общее ядро скоринга текста: одна леммизация/матчинг на весь модуль, из которой
    строятся оба публичных варианта (score_text / score_text_explained), чтобы не
    дублировать regex-матчинг и не давать им разойтись со временем.

    Возвращает (totals, dimension_lemmas, matched, cat_freq):
      - totals — нормированные (сумма=1.0) 10 значений ЦКМ;
      - dimension_lemmas[параметр] — леммы с ненулевым весом ИМЕННО по этому
        параметру в данном тексте (не нормировано, для explainability);
      - matched — плоский список всех совпавших лемм (как раньше в score_text);
      - cat_freq — нормированная частота категорий слов CSV.
    """
    zero = {k: 0.0 for k in CSV_COLUMNS}
    empty_dim: dict[str, list[str]] = {k: [] for k in CSV_COLUMNS}
    empty = (zero, empty_dim, [], {})
    if not text or not text.strip():
        return empty
    single_dict, phrase_dict, phrase_pattern, categories_dict = _load_index(lang)
    if not single_dict and not phrase_dict:
        return empty
    text_lower = text.lower()
    totals: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    dimension_lemmas: dict[str, list[str]] = {k: [] for k in CSV_COLUMNS}
    matched: list[str] = []
    cat_counts: dict[str, int] = {}

    def _add(lemma: str, weights: dict[str, float]) -> None:
        matched.append(lemma)
        for col in CSV_COLUMNS:
            w = weights.get(col, 0.0)
            totals[col] += w
            if w > 0:
                dimension_lemmas[col].append(lemma)
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

    return totals, dimension_lemmas, matched, cat_freq


def score_text(text: str, lang: LemmaLang = LemmaLang.ru) -> LemmaScoreResult:
    totals, _dimension_lemmas, matched, cat_freq = _score_text_full(text, lang)
    return totals, matched, cat_freq


def score_text_explained(text: str, lang: LemmaLang = LemmaLang.ru) -> LemmaScoreResultExplained:
    """
    Как score_text, но вместо плоского списка совпавших лемм возвращает разбивку
    по параметрам ЦКМ: dimension_lemmas[параметр] = леммы, давшие ему вес > 0 в
    этом тексте. Используется там, где нужна объяснимость (например, комбинированная
    ЦКМ по нескольким категориям — см. use_case/analyze/lemma_categories_combined.py).
    """
    totals, dimension_lemmas, _matched, cat_freq = _score_text_full(text, lang)
    return totals, dimension_lemmas, cat_freq


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


async def score_texts_batch_explained(
    texts: list[str], lang: LemmaLang = LemmaLang.ru
) -> list[LemmaScoreResultExplained]:
    loop = asyncio.get_running_loop()
    return list(
        await asyncio.gather(
            *[loop.run_in_executor(None, score_text_explained, text, lang) for text in texts]
        )
    )


# ── Дозапись новых лемм в CSV ────────────────────────────────────────────────


def clean_lemma(raw: str) -> str:
    """Публичная обёртка над нормализацией леммы — для сверки на дубли извне модуля."""
    return _clean_lemma(raw)


def existing_lemmas(lang: LemmaLang) -> set[str]:
    """Все леммы (одиночные слова + фразы), уже присутствующие в словаре `lang`."""
    single_dict, phrase_dict, _, _ = _load_index(lang)
    return set(single_dict) | set(phrase_dict)


def list_categories(lang: LemmaLang) -> list[str]:
    """
    Канонический список категорий словаря `lang`: все уникальные непустые теги
    из последней колонки CSV (лемма с полем вида "договор / воля" даёт два
    отдельных тега), без явного мусора ("nan" — артефакт выгрузки через
    pandas/Excel, встречается как пустая ячейка). Отсортировано по алфавиту.

    Используется, чтобы ограничить LLM выбором строго из уже существующих
    категорий при генерации новых кандидатных лемм (см. lemma_llm_extractor.py) —
    вместо того чтобы модель придумывала свои. Список не дедуплицирует опечатки
    /похожие теги (например "воля"/"волю") — это данные словаря как они есть;
    ручная чистка CSV не входит в эту задачу.
    """
    _single, _phrase, _pattern, categories_dict = _load_index(lang)
    cats: set[str] = set()
    for cat_list in categories_dict.values():
        for c in cat_list:
            c = c.strip()
            if c and c.casefold() != "nan":
                cats.add(c)
    return sorted(cats)


def count_lemmas_by_parameter(lang: LemmaLang) -> dict[str, int]:
    """
    Количество лемм словаря `lang` с ненулевым весом по каждому из 10
    параметров ЦКМ (CSV_COLUMNS) — просто счётчик, без самих лемм/весов.
    Одна лемма может учитываться сразу в нескольких параметрах, если у неё
    ненулевой вес по нескольким колонкам.
    """
    single_dict, phrase_dict, _pattern, _categories_dict = _load_index(lang)
    counts: dict[str, int] = {col: 0 for col in CSV_COLUMNS}
    for weights in (*single_dict.values(), *phrase_dict.values()):
        for col in CSV_COLUMNS:
            if weights.get(col, 0.0) > 0:
                counts[col] += 1
    return counts


_BLACKLIST_FILENAMES: dict[LemmaLang, str] = {
    LemmaLang.ru: "blacklist_ru.csv",
    LemmaLang.ru_un: "blacklist_ru_un.csv",
    LemmaLang.usa: "blacklist_usa.csv",
    LemmaLang.usa_un: "blacklist_usa_un.csv",
    LemmaLang.frg: "blacklist_frg.csv",
}


def _find_blacklist_path(lang: LemmaLang, *, create: bool = False) -> Path:
    """
    Как _find_csv, но для файла чёрного списка лемм: список лежит в отдельном
    файле per-lang (server/lemma/blacklist_{lang}.csv, одна лемма на строку),
    т.к. для разных базовых языков словаря (ru/usa/frg) это разные слова.

    create=True — если файл ещё нигде не найден, создать пустой в первой
    существующей директории из _LEMMA_DIRS (для первого add_to_blacklist).
    """
    return _find_in_lemma_dirs(_BLACKLIST_FILENAMES[lang], create=create)


@lru_cache(maxsize=None)
def _load_blacklist_raw(lang: LemmaLang) -> frozenset[str]:
    """Чистый (после _clean_lemma) набор лемм чёрного списка ОДНОГО базового lang (без merge)."""
    try:
        path = _find_blacklist_path(lang)
    except FileNotFoundError:
        return frozenset()
    encoding = _detect_encoding(path)
    with open(path, encoding=encoding, newline="") as fh:
        lines = fh.read().splitlines()
    return frozenset(_clean_lemma(line) for line in lines if line.strip())


def list_blacklist(lang: LemmaLang) -> list[str]:
    """
    Чёрный список лемм для `lang`, отсортированный по алфавиту. Для merged-языков
    (ru_merged/usa_merged) — объединение чёрных списков обеих компонент (сами
    merged не имеют своего файла, как и в append_lemmas/_load_index).
    """
    if lang in _MERGED_COMPONENTS:
        lang_a, lang_b = _MERGED_COMPONENTS[lang]
        combined = _load_blacklist_raw(lang_a) | _load_blacklist_raw(lang_b)
        return sorted(combined)
    return sorted(_load_blacklist_raw(lang))


def is_blacklisted(lemma: str, lang: LemmaLang) -> bool:
    """Есть ли лемма (после нормализации) в чёрном списке `lang`."""
    key = _clean_lemma(lemma)
    if not key:
        return False
    if lang in _MERGED_COMPONENTS:
        lang_a, lang_b = _MERGED_COMPONENTS[lang]
        return key in _load_blacklist_raw(lang_a) or key in _load_blacklist_raw(lang_b)
    return key in _load_blacklist_raw(lang)


def _append_lines(path: Path, encoding: str, lines: list[str]) -> None:
    """
    Дописать `lines` (по одной на строку) в конец `path`, гарантируя перевод
    строки перед новым контентом, если файл уже не пуст и не оканчивается на
    \n/\r — иначе первая новая строка слиплась бы с последней старой. Общая
    логика для add_to_blacklist и append_lemmas (append-ветка).
    """
    with open(path, "rb") as fh:
        fh.seek(0, 2)
        has_content = fh.tell() > 0
        needs_leading_newline = False
        if has_content:
            fh.seek(-1, 2)
            needs_leading_newline = fh.read(1) not in (b"\n", b"\r")

    with open(path, "a", encoding=encoding, newline="") as fh:
        if needs_leading_newline:
            fh.write("\n")
        fh.write("\n".join(lines) + "\n")


def add_to_blacklist(lang: LemmaLang, lemmas: list[str]) -> tuple[int, list[str]]:
    """
    Добавить леммы в чёрный список `lang` (append, без дублей).
    Возвращает (сколько добавлено, какие уже были в списке — эхом как передали).
    """
    if lang in _MERGED_COMPONENTS:
        raise MergedLangNotWritableError(
            f"'{lang.value}' — вычисляемый merged-словарь, свой чёрный список недоступен для записи"
        )
    existing = _load_blacklist_raw(lang)
    keys_seen: set[str] = set(existing)
    already: list[str] = []
    new_keys: list[str] = []
    for raw in lemmas:
        key = _clean_lemma(str(raw))
        if not key or key in keys_seen:
            if key:
                already.append(str(raw))
            continue
        keys_seen.add(key)
        new_keys.append(key)

    if new_keys:
        path = _find_blacklist_path(lang, create=True)
        has_content = path.exists() and path.stat().st_size > 0
        encoding = _detect_encoding(path) if has_content else "utf-8"
        _append_lines(path, encoding, new_keys)
        _load_blacklist_raw.cache_clear()
        logger.info("lemma_blacklist_appended", lang=lang.value, added=len(new_keys))

    return len(new_keys), already


def remove_from_blacklist(lang: LemmaLang, lemmas: list[str]) -> int:
    """Удалить леммы из чёрного списка `lang`. Возвращает, сколько реально было удалено."""
    if lang in _MERGED_COMPONENTS:
        raise MergedLangNotWritableError(
            f"'{lang.value}' — вычисляемый merged-словарь, свой чёрный список недоступен для записи"
        )
    to_remove = {_clean_lemma(str(x)) for x in lemmas}
    to_remove.discard("")
    try:
        path = _find_blacklist_path(lang)
    except FileNotFoundError:
        return 0

    encoding = _detect_encoding(path)
    with open(path, encoding=encoding, newline="") as fh:
        lines = [line for line in fh.read().splitlines() if line.strip()]
    kept = [line for line in lines if _clean_lemma(line) not in to_remove]
    removed = len(lines) - len(kept)
    if removed:
        with open(path, "w", encoding=encoding, newline="") as fh:
            for line in kept:
                fh.write(line + "\n")
        _load_blacklist_raw.cache_clear()
        logger.info("lemma_blacklist_removed", lang=lang.value, removed=removed)
    return removed


def _format_weight(value: object) -> str:
    """
    Число 0.0..1.0 → строка в стиле исходных CSV (запятая как разделитель, без
    хвостовых нулей). 2 знака после запятой — как в исходных словарях (напр.
    "0,17"), а не 4: избыточная точность из LLM/нормализации не должна попадать
    в CSV при записи через редактор лемм.
    """
    try:
        f = float(value)
    except (TypeError, ValueError):
        f = 0.0
    f = max(0.0, min(1.0, f))
    s = f"{f:.2f}".rstrip("0").rstrip(".")
    if s in ("", "-0"):
        s = "0"
    return s.replace(".", ",")


class MergedLangNotWritableError(ValueError):
    """*_merged языки — вычисляемая комбинация двух словарей, своего CSV-файла нет."""


def append_lemmas(lang: LemmaLang, items: list[dict]) -> tuple[int, int, list[str]]:
    """
    Добавить новые и обновить уже существующие леммы в CSV-словаре `lang` (upsert).

    items: [{"lemma": str, "weights": {col: float, ...}, "category": str}, ...]
    Возвращает (сколько_добавлено, сколько_обновлено, леммы_пропущенные_как_дубль_внутри_запроса).

    Если лемма уже есть в словаре — её старая строка удаляется и заменяется новой
    (а не молча игнорируется, как было раньше). Повтор одной и той же леммы дважды
    в одном вызове — второе вхождение пропускается (skipped), выигрывает первое.
    После записи кэш индекса сбрасывается — следующий score_text/extract_new_lemmas
    увидит обновлённые значения.
    """
    if lang in _MERGED_COMPONENTS:
        raise MergedLangNotWritableError(
            f"'{lang.value}' — вычисляемый merged-словарь (сумма двух других), нет своего CSV-файла"
        )

    path = _find_csv(lang)
    already = existing_lemmas(lang)

    skipped: list[str] = []
    new_lines: list[str] = []
    upsert_keys: set[str] = set()

    for item in items:
        lemma_raw = str(item.get("lemma", "")).strip()
        key = _clean_lemma(lemma_raw)
        if not key:
            continue
        if key in upsert_keys:
            skipped.append(lemma_raw)
            continue
        upsert_keys.add(key)

        weights = item.get("weights") or {}
        values = [_format_weight(weights.get(col, 0.0)) for col in CSV_COLUMNS]
        category = str(item.get("category", "")).strip()
        new_lines.append(";".join([lemma_raw, *values, category]))

    if not new_lines:
        return 0, 0, skipped

    updated_keys = upsert_keys & already
    added_count = len(upsert_keys) - len(updated_keys)

    encoding = _detect_encoding(path)
    # utf-8-sig пишет BOM при каждом первом write() потока — в append/write-режиме
    # это вставило бы второй BOM в файл. Файл уже содержит BOM, если он был.
    write_encoding = "utf-8" if encoding == "utf-8-sig" else encoding

    if updated_keys:
        # Часть лемм уже есть в файле — убираем их старые строки и переписываем
        # файл целиком вместе с новыми версиями. Без этого шага в файле остались
        # бы и старая, и новая строка для одной и той же леммы одновременно.
        with open(path, encoding=encoding, newline="") as fh:
            lines = fh.read().splitlines()
        if not lines:
            raise ValueError(f"CSV-файл словаря '{lang.value}' пуст или повреждён")
        header, body = lines[0], lines[1:]
        kept_body = [
            line for line in body
            if line.strip() and _clean_lemma(line.split(";", 1)[0]) not in updated_keys
        ]
        with open(path, "w", encoding=write_encoding, newline="") as fh:
            fh.write(header + "\n")
            for line in kept_body:
                fh.write(line + "\n")
            fh.write("\n".join(new_lines) + "\n")
    else:
        _append_lines(path, write_encoding, new_lines)

    _load_index.cache_clear()
    logger.info(
        "lemma_csv_appended",
        lang=lang.value,
        added=added_count,
        updated=len(updated_keys),
        skipped=len(skipped),
    )
    return added_count, len(updated_keys), skipped
