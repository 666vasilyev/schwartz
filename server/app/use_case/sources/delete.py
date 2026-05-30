from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import add_audit_log, soft_delete_source


async def execute(db: AsyncSession, source_id: int) -> None:
    deleted = await soft_delete_source(db, source_id)
    if not deleted:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    await add_audit_log(db, source_id, "deleted", previous={}, changes={})
