"""
Оценка ценностей Шварца (Theory of Basic Values) по тексту: один вызов LLM, JSON с числами 0.0–1.0.
После получения ответа значения нормализуются так, чтобы сумма = 1.0.
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

# Промпт: few-shot на русском — показывает модели ожидаемый формат и уровень детализации.
# Не использует response_format (breaking с thinking-моделями), JSON парсится через extract_json.
SCHWARTZ_LLM_SYSTEM = (
    "Оцени выраженность 10 ценностей Шварца в тексте. Шкала: 0.0 (не выражено) – 1.0 (очень сильно).\n\n"
    "Ключи и их смысл:\n"
    "self_direction = независимость, свобода выбора, творчество\n"
    "stimulation = новизна, риск, острые ощущения, приключения\n"
    "hedonism = удовольствие, радость, комфорт, наслаждение\n"
    "achievement = успех, амбиции, победа, достижение целей\n"
    "power = власть, контроль, статус, богатство, господство\n"
    "security = безопасность, стабильность, защита, порядок\n"
    "conformity = следование правилам, послушание, сдержанность\n"
    "tradition = обычаи, религия, наследие, почитание старших\n"
    "benevolence = забота о близких, семья, лояльность, дружба\n"
    "universalism = справедливость, экология, права человека, мир\n\n"
    "Пример:\n"
    'Текст: "Волонтёры высадили тысячу деревьев в городском парке, чтобы улучшить экологию."\n'
    'Ответ: {"self_direction":0.3,"stimulation":0.1,"hedonism":0.0,"achievement":0.4,'
    '"power":0.0,"security":0.2,"conformity":0.1,"tradition":0.0,'
    '"benevolence":0.5,"universalism":0.8}\n\n'
    "Верни ТОЛЬКО JSON-объект с 10 ключами, без markdown и пояснений."
)


def normalize_schwartz_payload(raw: object) -> dict[str, float]:
    """Привести ответ LLM к фиксированным ключам; значения 0.0..1.0, отсутствие → 0.0."""
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


def normalize_to_unit_sum(values: dict[str, float]) -> dict[str, float]:
    """Нормализовать так, чтобы сумма значений = 1.0.

    Если сумма ≤ 0 (все нули) — возвращаем как есть (равномерное распределение
    не имеет смысла без реальных данных).
    """
    total = sum(values.values())
    if total <= 0.0:
        return dict(values)
    return {k: round(v / total, 4) for k, v in values.items()}


async def extract_schwartz_values_from_text(
    text: str | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, float] | None:
    """
    Возвращает словарь из 10 ключей с дробями 0..1 (сумма = 1.0), либо None если текста нет.
    provider/model — per-request override (опционально).
    """
    if not text or not text.strip():
        return None
    t = text.strip()[:8000]
    # Ошибки LLM (HTTPException 502) пробрасываются наверх — клиент получает реальную ошибку
    result = await ask_llm_json(
        f"Текст:\n\n{t}",
        system=SCHWARTZ_LLM_SYSTEM,
        provider=provider,
        model=model,
        max_tokens=1024,
    )
    if not isinstance(result, dict):
        logger.warning("schwartz_llm_not_dict", type_=type(result).__name__)
        return {k: 0.0 for k in SCHWARTZ_KEYS}
    normalized = normalize_schwartz_payload(result)
    unit = normalize_to_unit_sum(normalized)
    max_key = max(unit, key=unit.get)
    logger.info(
        "schwartz_extracted",
        max_key=max_key,
        max_val=round(unit[max_key], 4),
        nonzero=sum(1 for v in unit.values() if v > 0),
    )
    return unit


def merge_details_with_schwartz(
    text_reason: str,
    schwartz: dict[str, float] | None,
) -> dict:
    d: dict = {"text_reason": text_reason}
    if schwartz is not None:
        d["schwartz_values"] = schwartz
    return d
