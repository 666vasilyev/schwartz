from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.analyzer import analyze_source_posts_in_memory
from app.infrastructure.repositories import (
    get_source_by_id,
    list_posts_by_owner_id,
    list_posts_by_source_id,
    replace_source_schwartz,
)
from app.presentation.schemas.analysis import SourceAnalyzeResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def execute(
    db: AsyncSession,
    source_id: int,
    *,
    limit: int | None,
) -> SourceAnalyzeResponse:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source id={source_id} not found",
        )

    if src.source_type == "rss":
        oid = None
        all_rows = await list_posts_by_source_id(db, source_id)
    else:
        if src.vk_owner_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="У источника не задан vk_owner_id (нужен collect или VK-токен при создании)",
            )
        oid = int(src.vk_owner_id)
        all_rows = await list_posts_by_owner_id(db, oid)

    n_total = len(all_rows)
    rows = all_rows[:limit] if limit is not None else all_rows

    logger.info(
        "analyze_source_request",
        source_id=source_id,
        source_kind=src.source_type,
        vk_owner_id=oid,
        posts_total=n_total,
        posts_in_run=len(rows),
    )
    batch = await analyze_source_posts_in_memory(rows)
    await replace_source_schwartz(db, source_id, batch.aggregate_schwartz)

    aggregate_rounded = {
        k: round(float(v), 4) for k, v in batch.aggregate_schwartz.items()
    }

    return SourceAnalyzeResponse(
        source_id=src.id,
        vk_owner_id=oid,
        posts_total_in_db=n_total,
        posts_in_run=len(rows),
        posts_analyzed=len(batch.posts),
        posts_skipped_empty_text=batch.skipped_empty_text,
        aggregate_schwartz=aggregate_rounded,
    )
