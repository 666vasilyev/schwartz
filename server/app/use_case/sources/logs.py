from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import (
    count_audit_logs,
    get_source_by_id,
    list_audit_logs,
)
from app.presentation.schemas.source import AuditLogListResponse, AuditLogRead


async def execute(
    db: AsyncSession,
    source_id: int,
    *,
    skip: int = 0,
    limit: int = 50,
) -> AuditLogListResponse:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    total = await count_audit_logs(db, source_id)
    entries = await list_audit_logs(db, source_id, skip=skip, limit=limit)
    return AuditLogListResponse(
        items=[AuditLogRead.model_validate(e) for e in entries],
        total=total,
        skip=skip,
        limit=limit,
    )
