"""
Общее ядро LLM-саммаризации набора текстов постов: title + summary + topics.

Раньше эта логика (промпт, системное сообщение, разбор ответа) жила только в
cluster_labeler.py (разметка сюжетных кластеров из алгоритмической
кластеризации). Вынесено сюда, чтобы её же переиспользовать для саммари по
ПРОИЗВОЛЬНОЙ выборке постов, которую пользователь собирает руками на фронте
(см. use_case/posts/summarize.py — POST /api/v1/posts/summary) — набор постов
там не привязан ни к какому StoryCluster.
"""
from __future__ import annotations

from app.infrastructure.clients.llm import ask_llm_json

MAX_CHARS_PER_POST = 800

SYSTEM_PROMPT = (
    "Ты помощник новостного редактора. На вход — несколько постов СМИ "
    "об одном событии. Сформулируй:\n"
    "  • title: короткий нейтральный заголовок сюжета (до 100 символов);\n"
    "  • summary: фактическое описание сюжета в 1–3 предложениях;\n"
    "  • topics: массив 1–4 коротких ярлыков (1–2 слова каждый), "
    "отражающих темы (например: \"политика\", \"энергетика\", \"конфликт\").\n"
    "Отвечай только валидным JSON в формате "
    "{\"title\": str, \"summary\": str, \"topics\": [str]}."
)


def build_summary_prompt(texts: list[str]) -> str:
    blocks = []
    for i, t in enumerate(texts, 1):
        t = (t or "").strip()
        if not t:
            continue
        blocks.append(f"[Пост {i}]\n{t[:MAX_CHARS_PER_POST]}")
    return "\n\n".join(blocks)


def parse_summary_result(result: dict) -> tuple[str | None, str | None, list[str]]:
    """(title, summary, topics) из сырого JSON-ответа LLM — та же нормализация,
    что раньше была инлайном в cluster_labeler.label_cluster."""
    title = str(result.get("title", "") or "").strip()[:512] or None
    summary = str(result.get("summary", "") or "").strip() or None
    raw_topics = result.get("topics") or []
    topics: list[str] = []
    if isinstance(raw_topics, list):
        for t in raw_topics:
            if not isinstance(t, str):
                continue
            t_clean = t.strip().lower()[:64]
            if t_clean and t_clean not in topics:
                topics.append(t_clean)
            if len(topics) >= 4:
                break
    return title, summary, topics


async def summarize_post_texts(
    texts: list[str],
    *,
    max_tokens: int = 400,
    provider: str | None = None,
    model: str | None = None,
) -> tuple[str | None, str | None, list[str]]:
    """
    Один LLM-вызов на весь набор текстов → (title, summary, topics).

    Бросает исключение при ошибке LLM / неразбираемом ответе — что с этим
    делать, решает вызывающий код (cluster_labeler молча пропускает кластер и
    попробует на следующей доразметке; для ручного саммари по постам — см.
    use_case/posts/summarize.py, там это превращается в HTTP 502).
    """
    prompt = build_summary_prompt(texts)
    result = await ask_llm_json(
        prompt, system=SYSTEM_PROMPT, max_tokens=max_tokens, provider=provider, model=model
    )
    return parse_summary_result(result)
