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

import re

from app.application.services.content.lemma_scorer import (
    CSV_COLUMNS,
    LemmaLang,
    clean_lemma,
    existing_lemmas,
    score_text,
)
from app.infrastructure.clients.llm import ask_llm_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

TARGET_COUNT = 10
_ATTEMPTS_MULTIPLIER = 2  # буфер на случай дублей/невалидных ответов от LLM
_MAX_TOKENS = 6144  # видимый ответ — один маленький JSON-объект; запас в основном
# под скрытые рассуждения модели (см. docstring выше)

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


def _build_system_prompt(exclude: list[str]) -> str:
    exclude_str = (
        ", ".join(exclude[-_MAX_EXCLUDE_IN_PROMPT:])
        if exclude
        else "(в этом тексте по словарю совпадений не найдено)"
    )
    return (
        "Ты — лингвист-аналитик, размечающий леммы для словаря Ценностной Картины Мира (ЦКМ).\n"
        f"В словаре 10 направлений (порядок важен — веса задаются позиционным массивом):\n{_COLUMNS_HINT}\n\n"
        "По тексту ниже подбери ОДНУ лемму (существительное или устойчивое "
        "словосочетание в начальной форме), которая характеризует текст по этим "
        "10 направлениям.\n\n"
        "Укажи ровно 10 чисел от 0.0 до 1.0 — по одному на каждое направление "
        "СТРОГО В ТОМ ЖЕ ПОРЯДКЕ, что в списке выше (1-е число = \"Безопасность\", "
        "..., 10-е = \"Свобода совести\"). Если направление не подходит — 0.0, не "
        "все направления обязаны быть ненулевыми. Плюс категория — одно-два слова "
        "через ' / ' в нижнем регистре (например: 'история / война').\n\n"
        "ВАЖНО — не предлагай эти леммы, они уже использованы:\n"
        f"{exclude_str}\n\n"
        "Не рассуждай пошагово и не объясняй ход мыслей — сразу выведи финальный "
        "результат.\n\n"
        "Верни ТОЛЬКО один JSON-объект (без markdown, без пояснений до/после) вида:\n"
        f'{{"lemma": "...", "weights": [{_ZEROS_EXAMPLE}], "category": "..."}}'
    )


def _normalize_weights(raw: object) -> dict[str, float]:
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
        return out

    if isinstance(raw, dict):
        for k, v in raw.items():
            canonical = _COLUMN_LOOKUP.get(re.sub(r"\s+", "", str(k)).casefold())
            if canonical is None:
                continue
            out[canonical] = _to_float(v)
        return out

    return out


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
    provider: str | None = None,
    model: str | None = None,
) -> tuple[list[dict], list[str]]:
    """
    Вернуть (новые_леммы, already_matched).

    новые_леммы — до `TARGET_COUNT` dict {"lemma", "weights", "category"},
    отфильтрованных от дублей со словарём `lang` и друг с другом.
    already_matched — леммы словаря, уже встретившиеся в тексте (что мы просили LLM не повторять).

    Одна лемма запрашивается за один вызов LLM (см. docstring модуля) — на плохо
    ответившем вызове теряется только одна лемма, а не весь батч.
    """
    _, matched, _ = score_text(text, lang)
    already = existing_lemmas(lang)

    t = (text or "").strip()[:8000]
    prompt = f"Текст:\n\n{t}"

    result: list[dict] = []
    seen: set[str] = set()
    exclude_running: list[str] = list(matched)
    max_attempts = TARGET_COUNT * _ATTEMPTS_MULTIPLIER
    attempts_used = 0

    for attempts_used in range(1, max_attempts + 1):
        if len(result) >= TARGET_COUNT:
            break

        system = _build_system_prompt(exclude_running)
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

        # Не повторять дальше, даже если саму лемму отбросим как дубль ниже.
        exclude_running.append(lemma_raw)

        if key in seen or key in already:
            continue
        seen.add(key)
        result.append(
            {
                "lemma": lemma_raw,
                "weights": _normalize_weights(item.get("weights")),
                "category": str(item.get("category", "")).strip(),
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
