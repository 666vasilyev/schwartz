from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import delete_source


async def execute(db: AsyncSession, source_id: int) -> None:
    ok = await delete_source(db, source_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Источник не найден",
        )
