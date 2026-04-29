from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.schwartz_values import SCHWARTZ_KEYS
from app.infrastructure.repositories import (
    get_source_by_id,
    get_source_schwartz_by_source_id,
)
from app.presentation.schemas.analysis import SourceStoredSchwartzResponse


async def execute(db: AsyncSession, source_id: int) -> SourceStoredSchwartzResponse:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Source id={source_id} not found",
        )
    row = await get_source_schwartz_by_source_id(db, source_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Сохранённого анализа для этого источника нет",
        )
    aggregate = {k: round(float(getattr(row, k)), 4) for k in SCHWARTZ_KEYS}
    return SourceStoredSchwartzResponse(
        source_id=src.id,
        vk_owner_id=int(src.vk_owner_id) if src.vk_owner_id is not None else None,
        aggregate_schwartz=aggregate,
        analyzed_at=row.analyzed_at,
    )
