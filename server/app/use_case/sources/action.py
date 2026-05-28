"""Unified source action use case.

Handles all status transitions and fetch triggers through a single entry point.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import JobType, SourceStatus
from app.infrastructure.repositories import (
    add_audit_log,
    get_source_by_id,
    set_source_status,
    update_source,
)
from app.presentation.schemas.collection_job import FetchRequest, HistoricalFetchRequest
from app.presentation.schemas.source import SourceActionRequest, SourceActionResponse, SourceRead
from app.use_case.collection import jobs as jobs_uc

# Целевой статус для каждого status-действия
_TARGET_STATUS: dict[str, SourceStatus] = {
    "enable": SourceStatus.ACTIVE,
    "disable": SourceStatus.DISABLED,
    "pause": SourceStatus.PAUSED,
}

# Статусы, при которых действие запрещено
_FORBIDDEN: dict[str, set[SourceStatus]] = {
    "enable": {SourceStatus.DELETED},
    "disable": {SourceStatus.DELETED},
    "pause": {SourceStatus.DELETED, SourceStatus.BLOCKED},
}


async def execute(
    db: AsyncSession,
    source_id: int,
    body: SourceActionRequest,
) -> SourceActionResponse:
    action = body.action

    if action in _TARGET_STATUS:
        return await _status_transition(db, source_id, action)
    if action == "reset_error":
        return await _reset_error(db, source_id)
    if action in ("fetch", "fetch_incremental"):
        return await _fetch(db, source_id, body)
    if action == "fetch_history":
        return await _fetch_history(db, source_id, body)

    # На практике недостижимо — Literal уже валидирует action в схеме
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        detail=f"Неизвестное действие: {action!r}",
    )


# ── Status transitions ─────────────────────────────────────────────────────


async def _status_transition(
    db: AsyncSession,
    source_id: int,
    action: str,
) -> SourceActionResponse:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    if row.status in _FORBIDDEN[action]:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Нельзя выполнить '{action}' для источника со статусом '{row.status}'",
        )

    target = _TARGET_STATUS[action]
    prev_status = row.status
    updated = await set_source_status(db, source_id, target.value)
    assert updated is not None

    await add_audit_log(
        db,
        source_id,
        action,
        previous={"status": prev_status},
        changes={"status": target.value},
    )
    return SourceActionResponse(action=action, source=SourceRead.model_validate(updated))


async def _reset_error(db: AsyncSession, source_id: int) -> SourceActionResponse:
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
    return SourceActionResponse(action="reset_error", source=SourceRead.model_validate(updated))


# ── Fetch triggers ─────────────────────────────────────────────────────────


async def _fetch(
    db: AsyncSession,
    source_id: int,
    body: SourceActionRequest,
) -> SourceActionResponse:
    job_type = (
        JobType.SCHEDULED_FETCH.value
        if body.action == "fetch_incremental"
        else JobType.MANUAL_FETCH.value
    )
    fetch_req = FetchRequest(
        limit=body.limit or 100,
        priority=body.priority,
        max_retries=body.max_retries,
        timeout_seconds=body.timeout_seconds,
        correlation_id=body.correlation_id,
        params=body.params,
    )
    job = await jobs_uc.fetch_source(db, source_id, fetch_req, job_type=job_type)
    return SourceActionResponse(action=body.action, job=job.model_dump())


async def _fetch_history(
    db: AsyncSession,
    source_id: int,
    body: SourceActionRequest,
) -> SourceActionResponse:
    hist_req = HistoricalFetchRequest(
        limit=body.limit or 1000,
        date_from=body.date_from,
        date_to=body.date_to,
        priority=body.priority,
        correlation_id=body.correlation_id,
    )
    job = await jobs_uc.fetch_source_history(db, source_id, hist_req)
    return SourceActionResponse(action=body.action, job=job.model_dump())
