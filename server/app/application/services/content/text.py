"""
Анализ текста поста/комментариев — только через LLM (без отдельного NLP/OCR/Whisper).
"""

from app.infrastructure.clients.llm import ask_llm_json
from app.infrastructure.prompts import load_prompt
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_CHARS = 8000

# Промпт вынесен в server/prompts/text_destructiveness_system.txt (см. app.infrastructure.prompts)


async def analyze_text(
    text: str | None,
    *,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[float, str]:
    if not text or not text.strip():
        return 0.0, "текст отсутствует"

    t = text.strip()[:_MAX_CHARS]
    # Ошибки LLM (HTTPException 502) пробрасываются наверх — клиент получает реальную ошибку
    result = await ask_llm_json(
        f"Текст:\n\n{t}",
        system=load_prompt("text_destructiveness_system"),
        provider=provider,
        model=model,
    )
    score = float(result.get("score", 0.0))
    score = max(0.0, min(1.0, score))
    reason = str(result.get("reason", "") or "—")
    logger.info("text_llm_done", score=round(score, 4))
    return score, reason
