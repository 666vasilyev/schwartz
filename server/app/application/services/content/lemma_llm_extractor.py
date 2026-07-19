"""
Извлечение новых лемм для словаря ЦКМ через LLM.

Идея: текст (например, выступление) сначала прогоняется через словарный метод
(`score_text`) — так мы узнаём, какие леммы словаря `lang` уже встретились в
этом тексте. LLM просят подобрать новые, не повторяющиеся с ними леммы,
характеризующие текст по тем же 10 направлениям ЦКМ, что и колонки CSV.
Полный словарь (тысячи строк) в промпт не передаётся — вместо этого дубли
дополнительно отсеиваются локально перед возвратом кандидатов.

По одной лемме за вызов LLM (а не пачкой): gemma4:31b тратит заметную и, судя по
всему, не сильно зависящую от объёма ответа часть бюджета токенов на скрытые
рассуждения, которые не попадают ни в content, ни в thinking (даже при
think=false). Просить сразу 10+ лемм — рискованно: видимый JSON обрывается на
середине (finish_reason=length). Один маленький ответ за вызов почти всегда
укладывается в бюджет; расплата — общее время растёт, потому что накладные
расходы на рассуждения платятся за каждый вызов заново.
"""
from __future__ import annotations

import difflib
import re

from app.application.services.content.lemma_scorer import (
    CSV_COLUMNS,
    LemmaLang,
    clean_lemma,
    existing_lemmas,
    list_blacklist,
    list_categories,
    score_text,
)
from app.application.services.content.schwartz_values import normalize_to_unit_sum
from app.infrastructure.clients.llm import ask_llm_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

TARGET_COUNT = 10
_ATTEMPTS_MULTIPLIER = 2  # буфер на случай дублей/невалидных ответов от LLM
_MAX_TOKENS = 6144  # видимый ответ — один маленький JSON-объект; запас в основном
# под скрытые рассуждения модели (см. docstring выше)

# Леммы длиннее — отбрасываются как невалидный кандидат (см. extract_new_lemmas):
# словарь ЦКМ оперирует отдельными словами и короткими устойчивыми
# словосочетаниями, а не произвольными фразами/предложениями.
_MAX_LEMMA_WORDS = 2

# Для fuzzy-сведения категории от LLM к существующей, если она не совпала точно
# (см. _normalize_category) — ниже порога считаем, что похожих категорий нет.
_CATEGORY_FUZZY_CUTOFF = 0.6

_COLUMNS_HINT = "\n".join(f"{i + 1}. {col}" for i, col in enumerate(CSV_COLUMNS))
_ZEROS_EXAMPLE = ", ".join("0.0" for _ in CSV_COLUMNS)

# Сколько уже использованных лемм максимум перечисляем в промпте как "не повторяй".
# Список растёт на каждой итерации (совпадения из словаря + всё, что LLM уже
# предложила в этом прогоне); слишком длинный список внутри system-промпта у
# thinking-моделей на практике повышает риск пустого/оборванного ответа.
_MAX_EXCLUDE_IN_PROMPT = 40

# Ключи весов (если модель всё же вернёт dict, а не массив) сверяются без учёта
# пробелов/регистра — модели не всегда воспроизводят колонки CSV символ-в-символ
# (напр. лишний/отсутствующий пробел вокруг "/").
_COLUMN_LOOKUP: dict[str, str] = {re.sub(r"\s+", "", col).casefold(): col for col in CSV_COLUMNS}


def _build_system_prompt(exclude: list[str], valid_categories: list[str]) -> str:
    exclude_str = (
        ", ".join(exclude[-_MAX_EXCLUDE_IN_PROMPT:])
        if exclude
        else "(в этом тексте по словарю совпадений не найдено)"
    )
    categories_str = ", ".join(valid_categories) if valid_categories else "(список категорий пуст)"
    return (
        "Ты — лингвист-аналитик, размечающий леммы для словаря Ценностной Картины Мира (ЦКМ).\n"
        f"В словаре 10 направлений (порядок важен — веса задаются позиционным массивом):\n{_COLUMNS_HINT}\n\n"
        "По тексту ниже подбери ОДНУ лемму (одно слово или устойчивое "
        f"словосочетание из МАКСИМУМ {_MAX_LEMMA_WORDS} слов, в начальной форме), "
        "которая характеризует текст по этим 10 направлениям.\n\n"
        "Укажи ровно 10 чисел от 0.0 до 1.0 — по одному на каждое направление "
        "СТРОГО В ТОМ ЖЕ ПОРЯДКЕ, что в списке выше (1-е число = \"Безопасность\", "
        "..., 10-е = \"Свобода совести\"). Если направление не подходит — 0.0, не "
        "все направления обязаны быть ненулевыми.\n\n"
        "Плюс категория — РОВНО ОДНА, строго из этого списка уже существующих "
        "категорий (ничего не придумывай, не комбинируй несколько через '/'):\n"
        f"{categories_str}\n\n"
        "ВАЖНО — не предлагай эти леммы, они уже использованы:\n"
        f"{exclude_str}\n\n"
        "Не рассуждай пошагово и не объясняй ход мыслей — сразу выведи финальный "
        "результат.\n\n"
        "Верни ТОЛЬКО один JSON-объект (без markdown, без пояснений до/после) вида:\n"
        f'{{"lemma": "...", "weights": [{_ZEROS_EXAMPLE}], "category": "..."}}'
    )


def _normalize_weights(raw: object) -> dict[str, float]:
    """
    Веса от LLM → фиксированные ключи CSV_COLUMNS, каждое значение 0.0..1.0,
    сумма по всем 10 направлениям нормализована к 1.0 (см. normalize_to_unit_sum
    в schwartz_values.py — та же логика, что и для оценки Шварца по тексту).

    Если LLM поставила везде 0.0 (сумма ≤ 0) — нормализовать не к чему,
    возвращаем как есть, не выдумывая равномерное распределение.

    Округление до 2 знаков после запятой — после normalize_to_unit_sum (у неё
    самой точность 4 знака, но для словаря лемм принят формат в 2 знака, как в
    исходных CSV, напр. "0,17"; normalize_to_unit_sum не трогаем, она общая с
    оценкой Шварца по тексту, где точность 4 знака остаётся прежней).
    """
    out: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}

    def _to_float(v: object) -> float:
        try:
            f = float(v)
        except (TypeError, ValueError):
            return 0.0
        return max(0.0, min(1.0, f))

    if isinstance(raw, list):
        # Позиционный формат: i-е число соответствует i-й колонке CSV_COLUMNS.
        for col, v in zip(CSV_COLUMNS, raw):
            out[col] = _to_float(v)
    elif isinstance(raw, dict):
        for k, v in raw.items():
            canonical = _COLUMN_LOOKUP.get(re.sub(r"\s+", "", str(k)).casefold())
            if canonical is None:
                continue
            out[canonical] = _to_float(v)

    unit = normalize_to_unit_sum(out)
    return {k: round(v, 2) for k, v in unit.items()}


def _normalize_category(raw: str, valid_categories: list[str]) -> str:
    """
    Приводит категорию от LLM к одной из valid_categories:
      1. Несколько через '/' — берём только первую часть (LLM просили не
         комбинировать, но не полагаемся на послушание).
      2. Точное совпадение (регистронезависимо) — используем каноническое
         написание из словаря.
      3. Иначе — ближайшее по строковому сходству (difflib, не смысловое)
         совпадение из valid_categories; если и такого нет — оставляем как
         есть, не отбрасываем кандидата и не выдумываем категорию из воздуха.
    """
    first = raw.split("/")[0].strip()
    if not first:
        return raw.strip()
    if not valid_categories:
        return first

    lookup = {c.casefold(): c for c in valid_categories}
    exact = lookup.get(first.casefold())
    if exact:
        return exact

    close = difflib.get_close_matches(
        first.casefold(), lookup.keys(), n=1, cutoff=_CATEGORY_FUZZY_CUTOFF
    )
    if close:
        return lookup[close[0]]
    return first


def _build_weight_assignment_prompt(lemma: str, valid_categories: list[str]) -> str:
    """
    Как _build_system_prompt, но лемма уже ЗАДАНА (не предлагается моделью) —
    используется для готовых кандидатов из частотного поиска по трендам (см.
    use_case/analyze/lemma_trend_candidates.py), где сама лемма определена
    частотным методом, а не LLM; LLM здесь нужна только для весов и категории.
    """
    categories_str = ", ".join(valid_categories) if valid_categories else "(список категорий пуст)"
    return (
        "Ты — лингвист-аналитик, размечающий леммы для словаря Ценностной Картины Мира (ЦКМ).\n"
        f"В словаре 10 направлений (порядок важен — веса задаются позиционным массивом):\n{_COLUMNS_HINT}\n\n"
        f'Дана лемма (слово или устойчивое словосочетание): "{lemma}".\n\n'
        "Укажи ровно 10 чисел от 0.0 до 1.0 — по одному на каждое направление "
        "СТРОГО В ТОМ ЖЕ ПОРЯДКЕ, что в списке выше (1-е число = \"Безопасность\", "
        "..., 10-е = \"Свобода совести\"), отражающих, насколько эта лемма характерна "
        "для каждого направления. Если направление не подходит — 0.0, не все "
        "направления обязаны быть ненулевыми.\n\n"
        "Плюс категория — РОВНО ОДНА, строго из этого списка уже существующих "
        "категорий (ничего не придумывай, не комбинируй несколько через '/'):\n"
        f"{categories_str}\n\n"
        "Не рассуждай пошагово и не объясняй ход мыслей — сразу выведи финальный "
        "результат.\n\n"
        "Верни ТОЛЬКО один JSON-объект (без markdown, без пояснений до/после) вида:\n"
        f'{{"weights": [{_ZEROS_EXAMPLE}], "category": "..."}}'
    )


async def assign_weights_to_lemmas(
    lemmas: list[str],
    lang: LemmaLang,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> list[dict]:
    """
    Для уже готового списка лемм (например, "эмпирических" кандидатов из
    частотного поиска по трендам — см. use_case/analyze/lemma_trend_candidates.py)
    попросить LLM подобрать веса по 10 направлениям ЦКМ и категорию.

    В отличие от extract_new_lemmas, сама лемма здесь ФИКСИРОВАНА и не
    предлагается моделью — только веса/категория. Один вызов LLM на лемму (см.
    docstring модуля про причину).

    Возвращает список dict {"lemma", "weights", "category"} в том же порядке,
    что и `lemmas`. Если вызов для конкретной леммы не удался (ошибка LLM или
    неразбираемый ответ) — для неё возвращаются нулевые веса и пустая
    категория; элемент не пропускается, чтобы вызывающий код мог сам решить,
    что делать (например, не передавать такую лемму в /lemma/append).
    """
    valid_categories = list_categories(lang)
    results: list[dict] = []

    for lemma in lemmas:
        weights: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
        category = ""
        system = _build_weight_assignment_prompt(lemma, valid_categories)
        try:
            raw = await ask_llm_json(
                f"Лемма: {lemma}",
                system=system,
                provider=provider,
                model=model,
                max_tokens=_MAX_TOKENS,
            )
            if isinstance(raw, dict):
                item: dict | None = raw
            elif isinstance(raw, list) and raw and isinstance(raw[0], dict):
                item = raw[0]
            else:
                item = None
            if item is not None:
                weights = _normalize_weights(item.get("weights"))
                category = _normalize_category(str(item.get("category", "")).strip(), valid_categories)
        except Exception as exc:
            logger.warning(
                "lemma_weight_assign_failed",
                lang=lang.value,
                lemma=lemma,
                error=str(exc)[:300],
            )
        results.append({"lemma": lemma, "weights": weights, "category": category})

    return results


def _extract_single_item(raw: object) -> dict | None:
    """LLM просили один объект, но некоторые модели всё равно оборачивают в массив/ключ."""
    if isinstance(raw, dict):
        for key in ("lemmas", "items", "result", "data"):
            value = raw.get(key)
            if isinstance(value, list) and value and isinstance(value[0], dict):
                return value[0]
        if "lemma" in raw:
            return raw
        return None
    if isinstance(raw, list) and raw and isinstance(raw[0], dict):
        return raw[0]
    return None


async def extract_new_lemmas(
    text: str,
    lang: LemmaLang,
    *,
    count: int = TARGET_COUNT,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[list[dict], list[str]]:
    """
    Вернуть (новые_леммы, already_matched).

    новые_леммы — до `count` dict {"lemma", "weights", "category"},
    отфильтрованных от дублей со словарём `lang` и друг с другом.
    already_matched — леммы словаря, уже встретившиеся в тексте (что мы просили LLM не повторять).

    Одна лемма запрашивается за один вызов LLM (см. docstring модуля) — на плохо
    ответившем вызове теряется только одна лемма, а не весь батч. Соответственно,
    чем больше `count`, тем больше последовательных вызовов LLM и тем дольше ответ.
    """
    target = max(1, count)
    _, matched, _ = score_text(text, lang)
    # Чёрный список объединяем со словарём: леммы из него не должны предлагаться
    # LLM повторно (как и уже существующие в словаре), см. /lemma/blacklist.
    already = existing_lemmas(lang) | set(list_blacklist(lang))
    valid_categories = list_categories(lang)

    t = (text or "").strip()[:8000]
    prompt = f"Текст:\n\n{t}"

    result: list[dict] = []
    seen: set[str] = set()
    exclude_running: list[str] = list(matched)
    max_attempts = target * _ATTEMPTS_MULTIPLIER
    attempts_used = 0

    for attempts_used in range(1, max_attempts + 1):
        if len(result) >= target:
            break

        system = _build_system_prompt(exclude_running, valid_categories)
        try:
            raw = await ask_llm_json(
                prompt,
                system=system,
                provider=provider,
                model=model,
                max_tokens=_MAX_TOKENS,
            )
        except Exception as exc:
            logger.warning(
                "lemma_extract_attempt_failed",
                lang=lang.value,
                attempt=attempts_used,
                error=str(exc)[:300],
            )
            continue

        item = _extract_single_item(raw)
        if item is None:
            logger.warning("lemma_extract_no_item", lang=lang.value, attempt=attempts_used)
            continue

        lemma_raw = str(item.get("lemma", "")).strip()
        key = clean_lemma(lemma_raw)
        if not key:
            continue

        # Не повторять дальше, даже если саму лемму отбросим как дубль/слишком
        # длинную ниже — иначе LLM будет упрямо предлагать её снова и снова.
        exclude_running.append(lemma_raw)

        if key in seen or key in already:
            continue
        if len(lemma_raw.split()) > _MAX_LEMMA_WORDS:
            logger.warning(
                "lemma_extract_too_long",
                lang=lang.value,
                lemma=lemma_raw,
                words=len(lemma_raw.split()),
            )
            continue
        seen.add(key)
        result.append(
            {
                "lemma": lemma_raw,
                "weights": _normalize_weights(item.get("weights")),
                "category": _normalize_category(
                    str(item.get("category", "")).strip(), valid_categories
                ),
            }
        )

    if len(result) < TARGET_COUNT:
        logger.warning(
            "lemma_extract_below_target",
            lang=lang.value,
            got=len(result),
            target=TARGET_COUNT,
            attempts_used=attempts_used,
        )
    else:
        logger.info("lemma_extract_done", lang=lang.value, new_lemmas=len(result), attempts_used=attempts_used)

    return result, matched
