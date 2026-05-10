from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import SourceStatus
from app.infrastructure.repositories import get_source_by_id
from app.presentation.schemas.source import SourceHealth

_HEALTHY_STATUSES = {SourceStatus.ACTIVE.value, SourceStatus.PAUSED.value}


async def execute(db: AsyncSession, source_id: int) -> SourceHealth:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    is_healthy = row.status in _HEALTHY_STATUSES and row.error_count == 0

    return SourceHealth(
        source_id=source_id,
        status=SourceStatus(row.status),
        is_healthy=is_healthy,
        error_count=row.error_count,
        last_fetch_at=row.last_fetch_at or row.last_run_at,
        last_success_at=row.last_success_at,
        last_error_at=row.last_error_at,
        next_fetch_at=row.next_fetch_at,
        error_message=row.error_message,
    )
