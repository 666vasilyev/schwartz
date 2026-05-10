from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import add_audit_log, get_source_by_id, soft_delete_source


async def execute(db: AsyncSession, source_id: int) -> None:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    ok = await soft_delete_source(db, source_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    await add_audit_log(
        db,
        source_id,
        "delete",
        previous={"status": row.status},
        changes={"status": "deleted"},
    )
