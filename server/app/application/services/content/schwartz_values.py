"""
Оценка ценностей Шварца (Theory of Basic Values) по тексту: один вызов LLM, JSON с числами 0.0–1.0.
"""
from __future__ import annotations

from app.infrastructure.clients.llm import ask_llm_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

# 10 мотивационно различимых ценностей (Schwartz) — ключи в JSON-ответе LLM
SCHWARTZ_KEYS: tuple[str, ...] = (
    "self_direction",  # Независимость, свобода, креатив
    "stimulation",  # Разнообразие, приключения, новизна
    "hedonism",  # Удовольствие, радость жизни
    "achievement",  # Успех, демонстрация компетентности
    "power",  # Социальный статус, власть, богатство, господство
    "security",  # Безопасность, стабильность, порядок, гармония
    "conformity",  # Сдержанность, послушание нормам, не причинять вреда
    "tradition",  # Соблюдение культурных/религиозных норм, смирение
    "benevolence",  # Забота о близких, доверие, близкие люди
    "universalism",  # Справедливость, толерантность, природа, всеобщий мир
)

# Промпт для LLM: не дублируйте имя старого impact-классификатора
SCHWARTZ_LLM_SYSTEM = f"""Ты оцениваешь, насколько в **данном фрагменте текста** (пост, объявление и т.п.) читаема или активируема каждая из **10 базовых ценностей Шварца (Schwartz)**, по шкале от **0.0** (почти нет) до **1.0** (очень сильно выражено). Учти формулировки, тон, призывы, темы, а не предположения о внешнем контексте, которого в тексте нет.

Смысл измерителей (кратко):
- self_direction — свобода мыслей, выбора, независимость, творчество
- stimulation — смена впечатлений, риск, крутые ощущения, новизна
- hedonism — удовольствие, кайф, комфорт «здесь и сейчас»
- achievement — соревнование, успех, демонстрация своих сил, цели, KPI
- power — власть, доминирование, статус, деньги как контроль, давление, «кто главный»
- security — национальная/личная/семейная безопасность, стабильность, предсказуемость
- conformity — норма, правила, «так не принято», сдержанность, соответствие
- tradition — вера, обычай, культовое «так положено», духовные традиции, почет старших
- benevolence — теплота, помощь **своим** (свои люди, семья, близкий круг)
- universalism — забота о **других** и планетарные темы, справедливость, равноправие, толерантность, экология

(В схеме JSON ключи строго на латинице, как ниже.)

**Обязательно** верни один JSON-объект, без markdown и без пояснений вне JSON, **ровно** с этими ключами (float 0.0..1.0):
{", ".join(f'"{k}"' for k in SCHWARTZ_KEYS)}

Значения — не «насколько ценно в абсолюте», а **насколько сильно этот смысл присутствует в присланном тексте**. Сумма значений **не** обязана быть 1.0.
"""


def normalize_schwartz_payload(raw: object) -> dict[str, float]:
    """Сведение ответа LLM к фиксированным ключам; значения 0.0..1.0, отсутствие → 0.0."""
    if not isinstance(raw, dict):
        return {k: 0.0 for k in SCHWARTZ_KEYS}
    out: dict[str, float] = {}
    for k in SCHWARTZ_KEYS:
        v = raw.get(k)
        if v is None:
            out[k] = 0.0
            continue
        try:
            f = float(v)
        except (TypeError, ValueError):
            f = 0.0
        out[k] = max(0.0, min(1.0, f))
    return out


async def extract_schwartz_values_from_text(
    text: str | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, float] | None:
    """
    Возвращает словарь из 10 ключей с дробями 0..1, либо None если текста нет.
    provider/model — per-request override (опционально).
    """
    if not text or not text.strip():
        return None
    t = text.strip()[:8000]
    try:
        result = await ask_llm_json(
            f"Проанализируй фрагмент и верни JSON по инструкции (см. system).\n\n---\n{t}",
            system=SCHWARTZ_LLM_SYSTEM,
            provider=provider,
            model=model,
        )
        if not isinstance(result, dict):
            logger.warning("schwartz_llm_not_dict", type_=type(result).__name__)
            return {k: 0.0 for k in SCHWARTZ_KEYS}
        normalized = normalize_schwartz_payload(result)
        logger.info("schwartz_extracted", max_key=max(normalized, key=normalized.get))
        return normalized
    except Exception as exc:
        logger.warning("schwartz_extraction_failed", error=str(exc))
        return {k: 0.0 for k in SCHWARTZ_KEYS}


def merge_details_with_schwartz(
    text_reason: str,
    schwartz: dict[str, float] | None,
) -> dict:
    d: dict = {"text_reason": text_reason}
    if schwartz is not None:
        d["schwartz_values"] = schwartz
    return d
