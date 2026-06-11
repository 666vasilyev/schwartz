"""
Анализ текста поста/комментариев — только через LLM (без отдельного NLP/OCR/Whisper).
"""

from app.infrastructure.clients.llm import ask_llm_json
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_CHARS = 8000

_SYSTEM = (
    "Ты эксперт по выявлению деструктивного, манипулятивного или опасного контента в тексте. "
    "Оцени уровень деструктивности по шкале от 0.0 (нейтрально) до 1.0 (максимальная деструктивность). "
    "Верни JSON-объект: {\"score\": <число 0.0..1.0>, \"reason\": <краткое пояснение на русском>}. "
    "Отвечай только валидным JSON."
)


async def analyze_text(
    text: str | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[float, str]:
    if not text or not text.strip():
        return 0.0, "текст отсутствует"

    t = text.strip()[:_MAX_CHARS]
    try:
        result = await ask_llm_json(
            f"Текст:\n\n{t}",
            system=_SYSTEM,
            provider=provider,
            model=model,
        )
        score = float(result.get("score", 0.0))
        score = max(0.0, min(1.0, score))
        reason = str(result.get("reason", "") or "—")
        logger.info("text_llm_done", score=round(score, 4))
        return score, reason
    except Exception as exc:
        logger.warning("text_llm_failed", provider=provider, model=model, error=str(exc))
        return 0.0, "ошибка анализа текста (LLM)"
