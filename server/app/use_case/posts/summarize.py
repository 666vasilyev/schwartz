"""POST /api/v1/posts/summary — саммари по постам, выбранным пользователем, через LLM."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.llm_summarizer import summarize_post_texts
from app.infrastructure.repositories import list_posts_by_ids
from app.presentation.schemas.post import PostSummaryResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_POST_IDS = 20


async def execute(db: AsyncSession, post_ids: list[int]) -> PostSummaryResponse:
    # dedupe, сохраняя порядок выбора пользователя (важно для промпта —
    # см. build_summary_prompt: посты нумеруются в этом порядке)
    unique_ids = list(dict.fromkeys(post_ids))
    if not unique_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="post_ids пуст")
    if len(unique_ids) > _MAX_POST_IDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Максимум {_MAX_POST_IDS} постов за раз",
        )

    rows = await list_posts_by_ids(db, unique_ids)
    by_id = {p.id: p for p in rows}
    found_ids = [pid for pid in unique_ids if pid in by_id]
    missing_ids = [pid for pid in unique_ids if pid not in by_id]
    empty_text_ids = [pid for pid in found_ids if not (by_id[pid].text or "").strip()]
    texts = [by_id[pid].text for pid in found_ids if (by_id[pid].text or "").strip()]

    if not texts:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Ни у одного из выбранных постов нет текста",
        )

    try:
        title, summary, topics = await summarize_post_texts(texts)
    except Exception as exc:
        logger.warning("posts_summary_failed", post_ids=unique_ids, error=str(exc)[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Не удалось получить саммари от LLM"
        ) from exc

    return PostSummaryResponse(
        title=title,
        summary=summary,
        topics=topics,
        posts_used=len(texts),
        missing_post_ids=missing_ids,
        empty_text_post_ids=empty_text_ids,
    )
