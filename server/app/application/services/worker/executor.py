"""
Job executor: maps job_type → actual work, updates counts, handles errors.
Traceback is written to structlog only; DB gets a public-safe error_message.
"""
from __future__ import annotations

import asyncio
import traceback
from datetime import datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import JobType, SourceStatus
from app.infrastructure.repositories import (
    add_job_log,
    finish_job_failure,
    finish_job_success,
    get_job_by_id,
    get_source_by_id,
    update_source,
)
from app.use_case.collect import get as collect_get
from app.use_case.sources.refresh_metadata import execute as refresh_metadata_exec
from app.utils.log_context import clear_context, set_job_context
from app.utils.log_events import Events
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def execute_job(db: AsyncSession, job_id: int, worker_id: str) -> None:
    """Execute a single job. Always updates the job record — never raises."""
    job = await get_job_by_id(db, job_id)
    if job is None:
        logger.error(
            Events.WORKER_UNEXPECTED_ERROR,
            message="Job record not found",
            job_id=job_id,
            worker_id=worker_id,
        )
        return

    set_job_context(
        job_id=job_id,
        source_id=job.source_id,
        worker_id=worker_id,
    )

    started_at = _utcnow()
    logger.info(
        Events.COLLECTION_JOB_STARTED,
        message=f"Job {job_id} started on {worker_id}",
        job_id=job_id,
        job_type=job.job_type,
        source_id=job.source_id,
        worker_id=worker_id,
        retry_count=job.retry_count,
    )
    await add_job_log(db, job_id, f"Начало выполнения на worker {worker_id}", level="info")
    await db.commit()

    try:
        result = await asyncio.wait_for(
            _dispatch(db, job_id, job.job_type, job.source_id, job.params or {}),
            timeout=float(job.timeout_seconds),
        )
    except asyncio.TimeoutError:
        duration_ms = int((_utcnow() - started_at).total_seconds() * 1000)
        logger.warning(
            Events.COLLECTION_JOB_TIMEOUT,
            message=f"Job {job_id} timed out after {job.timeout_seconds}s",
            job_id=job_id,
            source_id=job.source_id,
            worker_id=worker_id,
            timeout_seconds=job.timeout_seconds,
            duration_ms=duration_ms,
        )
        await add_job_log(
            db, job_id, f"Таймаут {job.timeout_seconds}с", level="error",
            data={"timeout_seconds": job.timeout_seconds},
        )
        await finish_job_failure(
            db, job_id,
            error_message="Задача превысила лимит времени выполнения",
            error_code="TIMEOUT",
        )
        await db.commit()
        clear_context()
        return
    except Exception as exc:
        duration_ms = int((_utcnow() - started_at).total_seconds() * 1000)
        tb = traceback.format_exc()
        logger.error(
            Events.COLLECTION_JOB_FAILED,
            message=f"Job {job_id} failed: {type(exc).__name__}",
            job_id=job_id,
            source_id=job.source_id,
            worker_id=worker_id,
            error_code=type(exc).__name__,
            error_message=str(exc)[:500],
            duration_ms=duration_ms,
            retry_count=job.retry_count,
            traceback=tb,
        )
        safe_msg = _safe_error(exc)
        await add_job_log(db, job_id, safe_msg, level="error")
        await finish_job_failure(db, job_id, error_message=safe_msg, error_code=type(exc).__name__)
        await db.commit()
        clear_context()
        return

    duration_ms = int((_utcnow() - started_at).total_seconds() * 1000)
    await finish_job_success(
        db,
        job_id,
        fetched_count=result.get("fetched_count", 0),
        saved_count=result.get("saved_count", 0),
        duplicate_count=result.get("duplicate_count", 0),
        skipped_count=result.get("skipped_count", 0),
        result=result,
    )
    await add_job_log(
        db, job_id, "Выполнено успешно", level="info",
        data={"saved": result.get("saved_count", 0), "fetched": result.get("fetched_count", 0)},
    )
    await db.commit()

    logger.info(
        Events.COLLECTION_JOB_FINISHED,
        message=f"Job {job_id} finished successfully",
        job_id=job_id,
        source_id=job.source_id,
        worker_id=worker_id,
        status="success",
        duration_ms=duration_ms,
        fetched_count=result.get("fetched_count", 0),
        saved_count=result.get("saved_count", 0),
        duplicate_count=result.get("duplicate_count", 0),
        skipped_count=result.get("skipped_count", 0),
        failed_count=result.get("failed_count", 0),
        retry_count=job.retry_count,
    )
    clear_context()


async def _dispatch(
    db: AsyncSession,
    job_id: int,
    job_type: str,
    source_id: int | None,
    params: dict,
) -> dict:
    if job_type in (
        JobType.MANUAL_FETCH.value,
        JobType.SCHEDULED_FETCH.value,
        JobType.HISTORICAL_FETCH.value,
        JobType.RETRY_FAILED.value,
    ):
        return await _run_collect(db, job_id, source_id, params)
    elif job_type == JobType.METADATA_REFRESH.value:
        return await _run_metadata_refresh(db, source_id)
    elif job_type == JobType.MEDIA_DOWNLOAD.value:
        return {"status": "not_implemented", "message": "Медиа-скачивание ещё не реализовано"}
    else:
        return {"status": "unknown_job_type", "job_type": job_type}


async def _run_collect(
    db: AsyncSession,
    job_id: int,
    source_id: int | None,
    params: dict,
) -> dict:
    if source_id is None:
        raise ValueError("source_id обязателен для задач сбора")

    src = await get_source_by_id(db, source_id)
    platform = src.source_type if src else None
    limit = int(params.get("limit", 100))
    use_mock = bool(params.get("use_mock", False))

    logger.info(
        Events.COLLECTION_VK_FETCH_STARTED if platform == "vk" else Events.COLLECTION_NORMALIZE_STARTED,
        message=f"Collecting source {source_id}",
        source_id=source_id,
        platform=platform,
        job_id=job_id,
        limit=limit,
    )

    await add_job_log(
        db, job_id, f"Запуск сбора для источника {source_id}",
        level="info", data={"limit": limit},
    )

    response = await collect_get.execute(
        db, source_id=source_id, limit=limit, use_mock=use_mock
    )

    total = getattr(response, "total", 0)
    saved = getattr(response, "saved_to_db", 0)
    fetched = len(getattr(response, "posts", []))
    dup = fetched - saved

    if src is not None:
        interval = src.fetch_interval_minutes or 60
        next_fetch = datetime.now(tz=timezone.utc) + timedelta(minutes=interval)
        await update_source(db, source_id, next_fetch_at=next_fetch)

    event = Events.COLLECTION_VK_FETCH_FINISHED if platform == "vk" else Events.COLLECTION_DEDUP_FINISHED
    logger.info(
        event,
        message=f"Collection done for source {source_id}",
        source_id=source_id,
        platform=platform,
        job_id=job_id,
        fetched_count=fetched,
        saved_count=saved,
        duplicate_count=max(0, dup),
    )

    return {
        "source_id": source_id,
        "fetched_count": fetched,
        "saved_count": saved,
        "duplicate_count": max(0, dup),
        "total": total,
    }


async def _run_metadata_refresh(db: AsyncSession, source_id: int | None) -> dict:
    if source_id is None:
        raise ValueError("source_id обязателен для metadata_refresh")
    result = await refresh_metadata_exec(db, source_id)
    return {
        "source_id": source_id,
        "updated": result.updated,
        "source_metadata": result.source_metadata,
    }


def _safe_error(exc: Exception) -> str:
    """Return a public-safe error message without stack trace or file paths."""
    name = type(exc).__name__
    msg = str(exc)
    if len(msg) > 500:
        msg = msg[:500] + "…"
    return f"{name}: {msg}"
