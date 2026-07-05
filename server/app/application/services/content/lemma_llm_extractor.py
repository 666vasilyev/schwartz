"""
Извлечение новых лемм для словаря ЦКМ через LLM.

Идея: текст (например, выступление) сначала прогоняется через словарный метод
(`score_text`) — так мы узнаём, какие леммы словаря `lang` уже встретились в
этом тексте. LLM просят подобрать новые, не повторяющиеся с ними леммы,
характеризующие текст по тем же 10 направлениям ЦКМ, что и колонки CSV.
Полный словарь (тысячи строк) в промпт не передаётся — вместо этого дубли
дополнительно отсеиваются локально перед возвратом кандидатов.
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
_REQUEST_COUNT = 15  # с запасом: часть кандидатов может отсеяться как дубль

_COLUMNS_HINT = "\n".join(f"{i + 1}. {col}" for i, col in enumerate(CSV_COLUMNS))
_WEIGHTS_EXAMPLE = ", ".join(f'"{c}": 0.0' for c in CSV_COLUMNS)

# Ключи весов сверяются без учёта пробелов/регистра — модели не всегда
# воспроизводят колонки CSV символ-в-символ (напр. лишний/отсутствующий пробел
# вокруг "/").
_COLUMN_LOOKUP: dict[str, str] = {re.sub(r"\s+", "", col).casefold(): col for col in CSV_COLUMNS}


def _build_system_prompt(exclude: list[str]) -> str:
    exclude_str = ", ".join(exclude[:200]) if exclude else "(в этом тексте по словарю совпадений не найдено)"
    return (
        "Ты — лингвист-аналитик, размечающий леммы для словаря Ценностной Картины Мира (ЦКМ).\n"
        f"В словаре 10 направлений:\n{_COLUMNS_HINT}\n\n"
        f"По тексту ниже подбери {_REQUEST_COUNT} НЕПОВТОРЯЮЩИХСЯ ДРУГ С ДРУГОМ лемм "
        "(существительные или устойчивые словосочетания в начальной форме), которые "
        "характеризуют текст по этим 10 направлениям.\n\n"
        "Для каждой леммы укажи вес от 0.0 до 1.0 по каждому из 10 направлений (насколько "
        "оно выражено этой леммой; если направление не подходит — 0.0, не все направления "
        "обязаны быть ненулевыми) и категорию — одно-два слова через ' / ' в нижнем регистре "
        "(например: 'история / война').\n\n"
        "ВАЖНО — не предлагай эти леммы, они уже есть в словаре и уже встретились в тексте:\n"
        f"{exclude_str}\n\n"
        "Если в самом тексте не находится 15 явных подходящих слов — не останавливайся, "
        "подбери максимально близкие по смыслу к тексту леммы, но не повторяй леммы из "
        "списка выше и не повторяй леммы между собой.\n\n"
        "Верни ТОЛЬКО JSON-массив (без markdown, без пояснений до/после) из объектов вида:\n"
        f'{{"lemma": "...", "weights": {{{_WEIGHTS_EXAMPLE}}}, "category": "..."}}'
    )


def _normalize_weights(raw: object) -> dict[str, float]:
    out: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    if not isinstance(raw, dict):
        return out
    for k, v in raw.items():
        canonical = _COLUMN_LOOKUP.get(re.sub(r"\s+", "", str(k)).casefold())
        if canonical is None:
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            continue
        out[canonical] = max(0.0, min(1.0, f))
    return out


def _extract_candidates(raw: object) -> list[dict]:
    if isinstance(raw, list):
        return [item for item in raw if isinstance(item, dict)]
    if isinstance(raw, dict):
        for key in ("lemmas", "items", "result", "data"):
            value = raw.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    return []


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
    """
    _, matched, _ = score_text(text, lang)
    already = existing_lemmas(lang)

    system = _build_system_prompt(matched)
    t = (text or "").strip()[:8000]
    raw = await ask_llm_json(
        f"Текст:\n\n{t}",
        system=system,
        provider=provider,
        model=model,
        max_tokens=3072,
    )
    candidates = _extract_candidates(raw)

    seen: set[str] = set()
    result: list[dict] = []
    for item in candidates:
        lemma_raw = str(item.get("lemma", "")).strip()
        if not lemma_raw:
            continue
        key = clean_lemma(lemma_raw)
        if not key or key in seen or key in already:
            continue
        seen.add(key)
        result.append(
            {
                "lemma": lemma_raw,
                "weights": _normalize_weights(item.get("weights")),
                "category": str(item.get("category", "")).strip(),
            }
        )
        if len(result) >= TARGET_COUNT:
            break

    if len(result) < TARGET_COUNT:
        logger.warning(
            "lemma_extract_below_target",
            lang=lang.value,
            got=len(result),
            target=TARGET_COUNT,
            candidates_received=len(candidates),
        )
    else:
        logger.info("lemma_extract_done", lang=lang.value, new_lemmas=len(result))

    return result, matched
