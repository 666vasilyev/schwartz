from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id
from app.presentation.schemas.source import SourceRead


async def execute(db: AsyncSession, source_id: int) -> SourceRead:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Источник не найден",
        )
    return SourceRead.model_validate(row)
