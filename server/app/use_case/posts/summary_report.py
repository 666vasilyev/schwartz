"""
POST /api/v1/posts/summary/report — отчёт (DOCX/PDF) по постам, выбранным
пользователем: LLM-саммари (переиспользует ту же логику, что и
POST /api/v1/posts/summary) + ЦКМ-аналитика (словарный метод) по той же
выборке, см. app/application/services/content/post_report.py.
"""
from __future__ import annotations

from typing import Literal

from fastapi import HTTPException, status
from fastapi.responses import Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang
from app.application.services.content.post_report import build_post_report_data
from app.application.services.content.report_docx import render_report_docx
from app.application.services.content.report_pdf import render_report_pdf
from app.infrastructure.repositories import list_posts_with_source_by_ids
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_POST_IDS = 20

_MEDIA_TYPES = {
    "docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "pdf": "application/pdf",
}


async def execute(
    db: AsyncSession,
    post_ids: list[int],
    *,
    lang: LemmaLang,
    fmt: Literal["docx", "pdf"],
    preset_title: str | None = None,
    preset_summary: str | None = None,
    preset_topics: list[str] | None = None,
) -> Response:
    # dedupe, сохраняя порядок выбора пользователя (важно — см. summarize.py: тот
    # же порядок используется в промпте саммари и здесь же в таблице постов)
    unique_ids = list(dict.fromkeys(post_ids))
    if not unique_ids:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="post_ids пуст")
    if len(unique_ids) > _MAX_POST_IDS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Максимум {_MAX_POST_IDS} постов за раз",
        )

    rows = await list_posts_with_source_by_ids(db, unique_ids)
    by_id = {row[0].id: row for row in rows}
    ordered_rows = [by_id[pid] for pid in unique_ids if pid in by_id]
    missing_ids = [pid for pid in unique_ids if pid not in by_id]

    if not ordered_rows:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ни один из указанных постов не найден"
        )

    try:
        data = await build_post_report_data(
            ordered_rows,
            lang=lang,
            posts_requested=len(unique_ids),
            missing_post_ids=missing_ids,
            preset_title=preset_title,
            preset_summary=preset_summary,
            preset_topics=preset_topics,
        )
    except Exception as exc:
        logger.warning("posts_summary_report_failed", post_ids=unique_ids, error=str(exc)[:300])
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY, detail="Не удалось получить саммари от LLM"
        ) from exc

    # Если саммари уже дано с экрана — отчёт всё равно валиден, даже если по
    # текущим текстам постов ЦКМ не посчиталась (например, посты успели
    # измениться в БД). Без preset_summary саммари строится из этих же
    # текстов, так что пустой набор текстов означает, что строить нечего.
    if data.posts_used == 0 and not preset_summary:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Ни у одного из выбранных постов нет текста"
        )

    if fmt == "docx":
        content = render_report_docx(data)
    else:
        content = render_report_pdf(data)

    filename = f"report_{data.generated_at:%Y%m%d_%H%M%S}.{fmt}"
    return Response(
        content=content,
        media_type=_MEDIA_TYPES[fmt],
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
