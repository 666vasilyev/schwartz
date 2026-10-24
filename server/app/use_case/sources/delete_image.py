"""DELETE /api/v1/sources/{id}/image — удалить изображение источника."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id, update_source
from app.infrastructure.storage.source_images import delete_source_image_file


async def execute(db: AsyncSession, source_id: int) -> None:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    delete_source_image_file(src.image_filename)
    await update_source(db, source_id, image_filename=None, image_updated_at=None)
    await db.commit()
