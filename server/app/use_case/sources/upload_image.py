"""POST /api/v1/sources/{id}/image — загрузить/заменить изображение источника."""
from __future__ import annotations

from datetime import datetime, timezone

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id, update_source
from app.infrastructure.storage.source_images import save_source_image
from app.presentation.schemas.source import SourceRead


async def execute(db: AsyncSession, source_id: int, file: UploadFile) -> SourceRead:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    filename = await save_source_image(source_id, file)
    row = await update_source(
        db,
        source_id,
        image_filename=filename,
        image_updated_at=datetime.now(tz=timezone.utc),
    )
    await db.commit()
    return SourceRead.model_validate(row)
