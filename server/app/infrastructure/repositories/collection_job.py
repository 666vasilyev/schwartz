"""Repository for CollectionJob, CollectionJobLog, DeadLetterJob."""
from __future__ import annotations

import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import (
    CollectionJob,
    CollectionJobLog,
    DeadLetterJob,
    JobStatus,
    Source,
)

_ACTIVE_STATUSES = (JobStatus.QUEUED.value, JobStatus.RUNNING.value, JobStatus.CREATED.value)
_TERMINAL_STATUSES = (
    JobStatus.SUCCESS.value,
    JobStatus.PARTIAL_SUCCESS.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
    JobStatus.TIMEOUT.value,
)

# Backoff config
_BACKOFF_BASE_SECONDS = 30
_BACKOFF_MAX_SECONDS = 3600


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _next_retry_at(retry_count: int) -> datetime:
    delay = min(_BACKOFF_BASE_SECONDS * (2**retry_count), _BACKOFF_MAX_SECONDS)
    jitter = random.uniform(0, 30)
    return _utcnow() + timedelta(seconds=delay + jitter)


# ── CRUD ────────────────────────────────────────────────────────────────────


async def create_job(
    db: AsyncSession,
    *,
    job_type: str,
    source_id: int | None = None,
    trigger_type: str = "manual",
    priority: int = 5,
    requested_limit: int | None = None,
    max_retries: int = 3,
    timeout_seconds: int = 300,
    correlation_id: str | None = None,
    params: dict | None = None,
) -> CollectionJob:
    job = CollectionJob(
        source_id=source_id,
        job_type=job_type,
        status=JobStatus.QUEUED.value,
        trigger_type=trigger_type,
        priority=priority,
        requested_limit=requested_limit,
        max_retries=max_retries,
        timeout_seconds=timeout_seconds,
        correlation_id=correlation_id,
        params=params or {},
    )
    db.add(job)
    await db.flush()
    await db.refresh(job)
    return job


async def get_job_by_id(db: AsyncSession, job_id: int) -> CollectionJob | None:
    result = await db.execute(select(CollectionJob).where(CollectionJob.id == job_id))
    return result.scalar_one_or_none()


async def list_jobs(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    source_id: int | None = None,
    status: str | None = None,
    job_type: str | None = None,
    worker_id: str | None = None,
) -> list[CollectionJob]:
    q = select(CollectionJob).order_by(
        CollectionJob.priority.asc(), CollectionJob.created_at.desc()
    )
    if source_id is not None:
        q = q.where(CollectionJob.source_id == source_id)
    if status:
        q = q.where(CollectionJob.status == status)
    if job_type:
        q = q.where(CollectionJob.job_type == job_type)
    if worker_id:
        q = q.where(CollectionJob.worker_id == worker_id)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_jobs(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    status: str | None = None,
    job_type: str | None = None,
) -> int:
    q = select(func.count()).select_from(CollectionJob)
    if source_id is not None:
        q = q.where(CollectionJob.source_id == source_id)
    if status:
        q = q.where(CollectionJob.status == status)
    if job_type:
        q = q.where(CollectionJob.job_type == job_type)
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def update_job(
    db: AsyncSession,
    job_id: int,
    **kwargs: object,
) -> CollectionJob | None:
    job = await get_job_by_id(db, job_id)
    if job is None:
        return None
    for k, v in kwargs.items():
        setattr(job, k, v)
    await db.flush()
    await db.refresh(job)
    return job


async def cancel_job(db: AsyncSession, job_id: int) -> CollectionJob | None:
    job = await get_job_by_id(db, job_id)
    if job is None:
        return None
    if job.status in _TERMINAL_STATUSES:
        return job  # already terminal
    job.status = JobStatus.CANCELLED.value
    job.finished_at = _utcnow()
    await db.flush()
    await db.refresh(job)
    return job


# ── Queue operations ────────────────────────────────────────────────────────


async def pick_next_job(db: AsyncSession, worker_id: str) -> CollectionJob | None:
    """Pick one queued job atomically (SKIP LOCKED) and mark it running."""
    stmt = (
        select(CollectionJob)
        .where(
            CollectionJob.status == JobStatus.QUEUED.value,
            or_(
                CollectionJob.next_retry_at.is_(None),
                CollectionJob.next_retry_at <= func.now(),
            ),
        )
        .order_by(CollectionJob.priority.asc(), CollectionJob.created_at.asc())
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    result = await db.execute(stmt)
    job = result.scalar_one_or_none()
    if job is None:
        return None

    now = _utcnow()
    job.status = JobStatus.RUNNING.value
    job.worker_id = worker_id
    job.started_at = now
    await db.flush()
    return job


async def finish_job_success(
    db: AsyncSession,
    job_id: int,
    *,
    fetched_count: int = 0,
    saved_count: int = 0,
    duplicate_count: int = 0,
    skipped_count: int = 0,
    result: dict | None = None,
) -> CollectionJob | None:
    job = await get_job_by_id(db, job_id)
    if job is None:
        return None
    now = _utcnow()
    started = job.started_at or now
    job.status = JobStatus.SUCCESS.value
    job.finished_at = now
    job.duration_ms = int((now - started).total_seconds() * 1000)
    job.fetched_count = fetched_count
    job.saved_count = saved_count
    job.duplicate_count = duplicate_count
    job.skipped_count = skipped_count
    job.result = result
    job.error_message = None
    job.error_code = None
    await db.flush()
    await db.refresh(job)
    return job


async def finish_job_failure(
    db: AsyncSession,
    job_id: int,
    *,
    error_message: str,
    error_code: str | None = None,
    failed_count: int = 0,
) -> CollectionJob | None:
    """Mark job failed or re-queue for retry with exponential backoff."""
    job = await get_job_by_id(db, job_id)
    if job is None:
        return None
    now = _utcnow()
    started = job.started_at or now
    job.finished_at = now
    job.duration_ms = int((now - started).total_seconds() * 1000)
    job.failed_count = failed_count
    job.error_message = error_message[:2000]
    job.error_code = error_code

    if job.retry_count < job.max_retries:
        job.retry_count += 1
        job.status = JobStatus.QUEUED.value
        job.next_retry_at = _next_retry_at(job.retry_count)
        job.started_at = None
        job.finished_at = None
        job.worker_id = None
    else:
        job.status = JobStatus.FAILED.value
        # Move to dead-letter queue
        dlq = DeadLetterJob(
            original_job_id=job.id,
            source_id=job.source_id,
            job_type=job.job_type,
            params=job.params,
            retry_count=job.retry_count,
            error_message=error_message[:2000],
        )
        db.add(dlq)

    await db.flush()
    await db.refresh(job)
    return job


async def finish_job_timeout(db: AsyncSession, job_id: int) -> CollectionJob | None:
    """Mark job as timed out and potentially re-queue."""
    return await finish_job_failure(
        db,
        job_id,
        error_message="Задача превысила лимит времени выполнения",
        error_code="TIMEOUT",
    )


# ── Limits / concurrency guards ────────────────────────────────────────────


async def count_active_jobs_for_source(db: AsyncSession, source_id: int) -> int:
    q = select(func.count()).select_from(CollectionJob).where(
        CollectionJob.source_id == source_id,
        CollectionJob.status.in_(_ACTIVE_STATUSES),
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def count_active_jobs_for_platform(db: AsyncSession, platform: str) -> int:
    q = (
        select(func.count())
        .select_from(CollectionJob)
        .join(Source, CollectionJob.source_id == Source.id, isouter=True)
        .where(
            Source.platform == platform,
            CollectionJob.status.in_(_ACTIVE_STATUSES),
        )
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def count_active_jobs_for_worker(db: AsyncSession, worker_id: str) -> int:
    q = select(func.count()).select_from(CollectionJob).where(
        CollectionJob.worker_id == worker_id,
        CollectionJob.status == JobStatus.RUNNING.value,
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


# ── Queue stats ─────────────────────────────────────────────────────────────


async def get_queue_stats(db: AsyncSession) -> dict:
    rows = await db.execute(
        select(CollectionJob.status, func.count().label("cnt"))
        .group_by(CollectionJob.status)
    )
    by_status = {row.status: row.cnt for row in rows}
    return {
        "queued": by_status.get(JobStatus.QUEUED.value, 0),
        "running": by_status.get(JobStatus.RUNNING.value, 0),
        "created": by_status.get(JobStatus.CREATED.value, 0),
        "success": by_status.get(JobStatus.SUCCESS.value, 0),
        "failed": by_status.get(JobStatus.FAILED.value, 0),
        "cancelled": by_status.get(JobStatus.CANCELLED.value, 0),
        "timeout": by_status.get(JobStatus.TIMEOUT.value, 0),
        "partial_success": by_status.get(JobStatus.PARTIAL_SUCCESS.value, 0),
    }


# ── Stuck job detection / recovery ─────────────────────────────────────────


async def find_stuck_jobs(
    db: AsyncSession, *, stale_minutes: int = 30
) -> list[CollectionJob]:
    """Jobs stuck in 'running' state beyond their timeout + buffer."""
    threshold = _utcnow() - timedelta(minutes=stale_minutes)
    stmt = select(CollectionJob).where(
        CollectionJob.status == JobStatus.RUNNING.value,
        CollectionJob.started_at < threshold,
    )
    result = await db.execute(stmt)
    return list(result.scalars().all())


async def recover_stuck_jobs(
    db: AsyncSession, *, stale_minutes: int = 30
) -> list[int]:
    """Re-queue or fail stuck jobs. Returns list of affected job IDs."""
    stuck = await find_stuck_jobs(db, stale_minutes=stale_minutes)
    recovered_ids: list[int] = []
    for job in stuck:
        await finish_job_timeout(db, job.id)
        recovered_ids.append(job.id)
    return recovered_ids


# ── Logs ───────────────────────────────────────────────────────────────────


async def add_job_log(
    db: AsyncSession,
    job_id: int,
    message: str,
    *,
    level: str = "info",
    data: dict | None = None,
) -> CollectionJobLog:
    entry = CollectionJobLog(job_id=job_id, level=level, message=message, data=data)
    db.add(entry)
    await db.flush()
    return entry


async def list_job_logs(
    db: AsyncSession,
    job_id: int,
    *,
    skip: int = 0,
    limit: int = 100,
) -> list[CollectionJobLog]:
    q = (
        select(CollectionJobLog)
        .where(CollectionJobLog.job_id == job_id)
        .order_by(CollectionJobLog.id.asc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_job_logs(db: AsyncSession, job_id: int) -> int:
    q = select(func.count()).select_from(CollectionJobLog).where(
        CollectionJobLog.job_id == job_id
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


# ── Due sources ─────────────────────────────────────────────────────────────


async def find_due_sources(db: AsyncSession) -> list[Source]:
    """Sources where next_fetch_at <= now and status=active and no active job."""
    from app.infrastructure.db.orm.models import SourceStatus

    now = _utcnow()
    # Sources with next_fetch_at overdue or never fetched
    q = select(Source).where(
        Source.status == SourceStatus.ACTIVE.value,
        Source.deleted_at.is_(None),
        or_(
            Source.next_fetch_at.is_(None),
            Source.next_fetch_at <= now,
        ),
    )
    result = await db.execute(q)
    sources = list(result.scalars().all())

    # Filter out sources that already have active jobs
    due = []
    for src in sources:
        active = await count_active_jobs_for_source(db, src.id)
        if active == 0:
            due.append(src)
    return due
