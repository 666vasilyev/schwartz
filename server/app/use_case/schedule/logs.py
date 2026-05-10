"""Schedule log listing use case."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.schedule import (
    count_schedule_logs,
    list_schedule_logs,
)
from app.presentation.schemas.schedule import ScheduleLogListResponse, ScheduleLogRead


async def execute(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    rule_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> ScheduleLogListResponse:
    logs = await list_schedule_logs(
        db, source_id=source_id, rule_id=rule_id, skip=skip, limit=limit
    )
    total = await count_schedule_logs(db, source_id=source_id, rule_id=rule_id)
    return ScheduleLogListResponse(
        items=[ScheduleLogRead.model_validate(lg) for lg in logs],
        total=total,
    )
