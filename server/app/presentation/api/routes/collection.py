"""
Collection Jobs API — /api/v1/collection/*
16 endpoints per spec.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.worker.runner import worker as _worker
from app.presentation.api.dependencies import get_session
from app.presentation.schemas.collection_job import (
    BulkFetchRequest,
    BulkFetchResponse,
    CreateJobRequest,
    JobListResponse,
    JobLogListResponse,
    JobRead,
    JobResultResponse,
    QueueStats,
    RecoverResponse,
    StuckJobsResponse,
    WorkerState,
)
from app.use_case.collection import jobs as jobs_uc

router = APIRouter(prefix="/api/v1/collection", tags=["Collection Jobs"])


# ── Jobs CRUD ──────────────────────────────────────────────────────────────


@router.post(
    "/jobs",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать задачу сбора",
)
async def create_job(
    body: CreateJobRequest,
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.create(db, body)


@router.get(
    "/jobs",
    response_model=JobListResponse,
    summary="Список задач сбора",
)
async def list_jobs(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    source_id: int | None = Query(None),
    job_status: str | None = Query(None, alias="status"),
    job_type: str | None = Query(None),
    worker_id: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> JobListResponse:
    return await jobs_uc.list_all(
        db,
        skip=skip,
        limit=limit,
        source_id=source_id,
        job_status=job_status,
        job_type=job_type,
        worker_id=worker_id,
    )


@router.get(
    "/jobs/{job_id}",
    response_model=JobRead,
    summary="Получить задачу по ID",
)
async def get_job(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.get(db, job_id)


@router.post(
    "/jobs/{job_id}/cancel",
    response_model=JobRead,
    summary="Отменить задачу",
)
async def cancel_job(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.cancel(db, job_id)


@router.post(
    "/jobs/{job_id}/retry",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Повторить задачу (создаёт новую с типом retry_failed)",
)
async def retry_job(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.retry(db, job_id)


@router.get(
    "/jobs/{job_id}/logs",
    response_model=JobLogListResponse,
    summary="Логи выполнения задачи",
)
async def job_logs(
    job_id: int = Path(..., ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
) -> JobLogListResponse:
    return await jobs_uc.get_logs(db, job_id, skip=skip, limit=limit)


@router.get(
    "/jobs/{job_id}/result",
    response_model=JobResultResponse,
    summary="Результат выполнения задачи",
)
async def job_result(
    job_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> JobResultResponse:
    return await jobs_uc.get_result(db, job_id)


# ── Bulk / System fetch ────────────────────────────────────────────────────


@router.post(
    "/fetch/bulk",
    response_model=BulkFetchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Массовый запуск сбора по списку источников",
)
async def bulk_fetch(
    body: BulkFetchRequest,
    db: AsyncSession = Depends(get_session),
) -> BulkFetchResponse:
    return await jobs_uc.bulk_fetch(db, body)


@router.post(
    "/fetch/due",
    response_model=BulkFetchResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить сбор по источникам, у которых подошло время (next_fetch_at ≤ now)",
)
async def fetch_due(
    db: AsyncSession = Depends(get_session),
) -> BulkFetchResponse:
    return await jobs_uc.fetch_due(db)


# ── Monitoring ─────────────────────────────────────────────────────────────


@router.get(
    "/queue",
    response_model=QueueStats,
    summary="Состояние очереди задач",
)
async def queue_state(
    db: AsyncSession = Depends(get_session),
) -> QueueStats:
    return await jobs_uc.queue_state(db)


@router.get(
    "/workers",
    response_model=list[WorkerState],
    summary="Состояние worker-процессов",
)
async def workers_state() -> list[WorkerState]:
    return [
        WorkerState(
            worker_id=_worker.worker_id,
            running_jobs=_worker.running_jobs,
            max_concurrent=_worker.max_concurrent,
            is_running=_worker.is_running,
        )
    ]


@router.get(
    "/stuck",
    response_model=StuckJobsResponse,
    summary="Список зависших задач (running > stale_minutes)",
)
async def stuck_jobs(
    stale_minutes: int = Query(30, ge=1, le=1440),
    db: AsyncSession = Depends(get_session),
) -> StuckJobsResponse:
    return await jobs_uc.stuck_jobs(db, stale_minutes=stale_minutes)


@router.post(
    "/stuck/recover",
    response_model=RecoverResponse,
    summary="Восстановить зависшие задачи (timeout + retry/fail)",
)
async def recover_stuck(
    stale_minutes: int = Query(30, ge=1, le=1440),
    db: AsyncSession = Depends(get_session),
) -> RecoverResponse:
    return await jobs_uc.recover(db, stale_minutes=stale_minutes)
