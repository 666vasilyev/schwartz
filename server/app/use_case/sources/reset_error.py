from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import SourceStatus
from app.infrastructure.repositories import add_audit_log, get_source_by_id, update_source
from app.presentation.schemas.source import SourceRead


async def execute(db: AsyncSession, source_id: int) -> SourceRead:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if row.status != SourceStatus.ERROR:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Источник не в статусе error (текущий: {row.status})",
        )

    updated = await update_source(
        db,
        source_id,
        status=SourceStatus.ACTIVE.value,
        error_message=None,
        error_count=0,
    )
    assert updated is not None

    await add_audit_log(
        db,
        source_id,
        "reset_error",
        previous={"status": SourceStatus.ERROR.value, "error_count": row.error_count},
        changes={"status": SourceStatus.ACTIVE.value, "error_count": 0},
    )
    return SourceRead.model_validate(updated)
