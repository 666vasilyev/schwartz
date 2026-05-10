from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import SourceStatus
from app.infrastructure.repositories import add_audit_log, get_source_by_id, set_source_status
from app.presentation.schemas.source import SourceRead


async def execute(db: AsyncSession, source_id: int) -> SourceRead:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if row.status == SourceStatus.DELETED:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Источник удалён")

    prev_status = row.status
    updated = await set_source_status(db, source_id, SourceStatus.ACTIVE.value)
    assert updated is not None

    await add_audit_log(
        db,
        source_id,
        "enable",
        previous={"status": prev_status},
        changes={"status": SourceStatus.ACTIVE.value},
    )
    return SourceRead.model_validate(updated)
