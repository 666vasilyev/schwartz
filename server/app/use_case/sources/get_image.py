"""GET /api/v1/sources/{id}/image — отдать файл изображения источника."""
from __future__ import annotations

from pathlib import Path

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id
from app.infrastructure.storage.source_images import source_image_path


async def execute(db: AsyncSession, source_id: int) -> Path:
    src = await get_source_by_id(db, source_id)
    if src is None or not src.image_filename:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="У источника нет изображения")
    path = source_image_path(src.image_filename)
    if not path.is_file():
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Файл изображения не найден на диске")
    return path
