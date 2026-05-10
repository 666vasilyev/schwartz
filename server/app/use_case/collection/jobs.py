"""
All collection-job use cases in one module (operations are thin orchestration layer).
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import JobStatus, JobType, TriggerType
from app.infrastructure.repositories import (
    cancel_job,
    count_active_jobs_for_platform,
    count_active_jobs_for_source,
    count_job_logs,
    count_jobs,
    create_job,
    find_due_sources,
    find_stuck_jobs,
    get_job_by_id,
    get_queue_stats,
    get_source_by_id,
    list_job_logs,
    list_jobs,
    recover_stuck_jobs,
    update_job,
)
from app.presentation.schemas.collection_job import (
    BulkFetchRequest,
    BulkFetchResponse,
    CreateJobRequest,
    FetchRequest,
    HistoricalFetchRequest,
    JobListResponse,
    JobLogListResponse,
    JobLogRead,
    JobRead,
    JobResultResponse,
    QueueStats,
    RecoverResponse,
    StuckJobsResponse,
)

# Configurable limits (could come from settings)
MAX_ACTIVE_JOBS_PER_SOURCE = 3
MAX_ACTIVE_JOBS_PER_PLATFORM = 10


# ── Helpers ────────────────────────────────────────────────────────────────


async def _check_source_exists(db: AsyncSession, source_id: int) -> None:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")


async def _check_source_limits(db: AsyncSession, source_id: int, platform: str | None) -> None:
    active = await count_active_jobs_for_source(db, source_id)
    if active >= MAX_ACTIVE_JOBS_PER_SOURCE:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Источник уже имеет {active} активных задач (макс. {MAX_ACTIVE_JOBS_PER_SOURCE})",
        )
    if platform:
        platform_active = await count_active_jobs_for_platform(db, platform)
        if platform_active >= MAX_ACTIVE_JOBS_PER_PLATFORM:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Платформа {platform!r} уже имеет {platform_active} активных задач (макс. {MAX_ACTIVE_JOBS_PER_PLATFORM})",
            )


# ── CRUD ───────────────────────────────────────────────────────────────────


async def create(db: AsyncSession, body: CreateJobRequest) -> JobRead:
    if body.source_id is not None:
        src = await get_source_by_id(db, body.source_id)
        if src is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден"
            )
        await _check_source_limits(db, body.source_id, src.platform)

    job = await create_job(
        db,
        job_type=body.job_type.value,
        source_id=body.source_id,
        trigger_type=body.trigger_type.value,
        priority=body.priority,
        requested_limit=body.requested_limit,
        max_retries=body.max_retries,
        timeout_seconds=body.timeout_seconds,
        correlation_id=body.correlation_id,
        params=body.params,
    )
    return JobRead.model_validate(job)


async def list_all(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    source_id: int | None,
    job_status: str | None,
    job_type: str | None,
    worker_id: str | None,
) -> JobListResponse:
    total = await count_jobs(db, source_id=source_id, status=job_status, job_type=job_type)
    rows = await list_jobs(
        db,
        skip=skip,
        limit=limit,
        source_id=source_id,
        status=job_status,
        job_type=job_type,
        worker_id=worker_id,
    )
    return JobListResponse(
        items=[JobRead.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get(db: AsyncSession, job_id: int) -> JobRead:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return JobRead.model_validate(job)


async def cancel(db: AsyncSession, job_id: int) -> JobRead:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if job.status in (
        JobStatus.SUCCESS.value,
        JobStatus.FAILED.value,
        JobStatus.CANCELLED.value,
        JobStatus.TIMEOUT.value,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Нельзя отменить задачу со статусом {job.status}",
        )
    updated = await cancel_job(db, job_id)
    assert updated is not None
    return JobRead.model_validate(updated)


async def retry(db: AsyncSession, job_id: int) -> JobRead:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    if job.status not in (JobStatus.FAILED.value, JobStatus.TIMEOUT.value, JobStatus.CANCELLED.value):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Повтор возможен только для failed/timeout/cancelled задач (текущий: {job.status})",
        )
    # Create a new job with same params and RETRY trigger
    new_job = await create_job(
        db,
        job_type=JobType.RETRY_FAILED.value,
        source_id=job.source_id,
        trigger_type=TriggerType.RETRY.value,
        priority=job.priority,
        requested_limit=job.requested_limit,
        max_retries=job.max_retries,
        timeout_seconds=job.timeout_seconds,
        correlation_id=job.correlation_id,
        params={**(job.params or {}), "original_job_id": job.id, "original_job_type": job.job_type},
    )
    return JobRead.model_validate(new_job)


async def get_logs(
    db: AsyncSession,
    job_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> JobLogListResponse:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    total = await count_job_logs(db, job_id)
    entries = await list_job_logs(db, job_id, skip=skip, limit=limit)
    return JobLogListResponse(
        items=[JobLogRead.model_validate(e) for e in entries],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_result(db: AsyncSession, job_id: int) -> JobResultResponse:
    job = await get_job_by_id(db, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Задача не найдена")
    return JobResultResponse(
        job_id=job.id,
        status=job.status,
        result=job.result,
        fetched_count=job.fetched_count,
        saved_count=job.saved_count,
        duplicate_count=job.duplicate_count,
        skipped_count=job.skipped_count,
        failed_count=job.failed_count,
        duration_ms=job.duration_ms,
    )


# ── Fetch shortcuts ────────────────────────────────────────────────────────


async def fetch_source(
    db: AsyncSession,
    source_id: int,
    body: FetchRequest,
    *,
    job_type: str = JobType.MANUAL_FETCH.value,
) -> JobRead:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    await _check_source_limits(db, source_id, src.platform)

    params = dict(body.params or {})
    params["limit"] = body.limit

    job = await create_job(
        db,
        job_type=job_type,
        source_id=source_id,
        trigger_type=TriggerType.API.value,
        priority=body.priority,
        requested_limit=body.limit,
        max_retries=body.max_retries,
        timeout_seconds=body.timeout_seconds,
        correlation_id=body.correlation_id,
        params=params,
    )
    return JobRead.model_validate(job)


async def fetch_source_history(
    db: AsyncSession,
    source_id: int,
    body: HistoricalFetchRequest,
) -> JobRead:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    await _check_source_limits(db, source_id, src.platform)

    params: dict = {"limit": body.limit}
    if body.date_from:
        params["date_from"] = body.date_from.isoformat()
    if body.date_to:
        params["date_to"] = body.date_to.isoformat()

    job = await create_job(
        db,
        job_type=JobType.HISTORICAL_FETCH.value,
        source_id=source_id,
        trigger_type=TriggerType.API.value,
        priority=body.priority,
        requested_limit=body.limit,
        correlation_id=body.correlation_id,
        params=params,
    )
    return JobRead.model_validate(job)


async def bulk_fetch(
    db: AsyncSession,
    body: BulkFetchRequest,
) -> BulkFetchResponse:
    created: list[JobRead] = []
    errors: list[dict] = []

    for source_id in body.source_ids:
        try:
            async with db.begin_nested():
                req = FetchRequest(
                    limit=body.limit,
                    priority=body.priority,
                )
                result = await fetch_source(db, source_id, req)
                created.append(result)
        except Exception as exc:
            errors.append({"source_id": source_id, "detail": str(exc)})

    return BulkFetchResponse(created=created, errors=errors)


async def fetch_due(db: AsyncSession) -> BulkFetchResponse:
    """Create fetch jobs for all sources whose next_fetch_at has elapsed."""
    due_sources = await find_due_sources(db)
    created: list[JobRead] = []
    errors: list[dict] = []

    for src in due_sources:
        try:
            async with db.begin_nested():
                job = await create_job(
                    db,
                    job_type=JobType.SCHEDULED_FETCH.value,
                    source_id=src.id,
                    trigger_type=TriggerType.SCHEDULER.value,
                    priority=6,
                    requested_limit=100,
                    params={"limit": 100},
                )
                created.append(JobRead.model_validate(job))
        except Exception as exc:
            errors.append({"source_id": src.id, "detail": str(exc)})

    return BulkFetchResponse(created=created, errors=errors)


# ── Monitoring ─────────────────────────────────────────────────────────────


async def queue_state(db: AsyncSession) -> QueueStats:
    stats = await get_queue_stats(db)
    return QueueStats(
        **stats,
        total_active=stats["queued"] + stats["running"] + stats["created"],
    )


async def stuck_jobs(db: AsyncSession, *, stale_minutes: int = 30) -> StuckJobsResponse:
    jobs = await find_stuck_jobs(db, stale_minutes=stale_minutes)
    return StuckJobsResponse(
        items=[JobRead.model_validate(j) for j in jobs],
        total=len(jobs),
    )


async def recover(db: AsyncSession, *, stale_minutes: int = 30) -> RecoverResponse:
    ids = await recover_stuck_jobs(db, stale_minutes=stale_minutes)
    return RecoverResponse(recovered_count=len(ids), job_ids=ids)
