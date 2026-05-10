"""
Sources management API — /api/v1/sources
All 20 endpoints per spec.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, Path, Query, Response, UploadFile, status
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.source import (
    AuditLogListResponse,
    BulkCreateRequest,
    BulkCreateResponse,
    BulkUpdateRequest,
    BulkUpdateResponse,
    JobListResponse,
    SourceCreateRequest,
    SourceHealth,
    SourceListResponse,
    SourceRead,
    SourceRefreshMetadataResponse,
    SourceStats,
    SourceUpdateRequest,
    SourceValidateResponse,
)
from app.use_case.sources import delete as delete_uc
from app.use_case.sources import disable as disable_uc
from app.use_case.sources import enable as enable_uc
from app.use_case.sources import export_sources as export_uc
from app.use_case.sources import get as get_uc
from app.use_case.sources import get_all as get_all_uc
from app.use_case.sources import health as health_uc
from app.use_case.sources import import_sources as import_uc
from app.use_case.sources import logs as logs_uc
from app.use_case.sources import patch as patch_uc
from app.use_case.sources import pause as pause_uc
from app.use_case.sources import post as post_uc
from app.use_case.sources import refresh_metadata as refresh_metadata_uc
from app.use_case.sources import reset_error as reset_error_uc
from app.use_case.sources import source_posts as source_posts_uc
from app.use_case.sources import stats as stats_uc
from app.use_case.sources import validate as validate_uc
from app.use_case.sources import bulk_create as bulk_create_uc
from app.use_case.sources import bulk_update as bulk_update_uc
from app.presentation.schemas.collection_job import FetchRequest, HistoricalFetchRequest, JobRead
from app.use_case.collection import jobs as jobs_uc
from app.infrastructure.db.orm.models import JobType

router = APIRouter(prefix="/api/v1/sources", tags=["Sources"])


# ── Collection endpoints (must come before /{source_id}) ──────────────────


@router.post(
    "/bulk",
    response_model=BulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Массово добавить источники",
)
async def bulk_create_sources(
    body: BulkCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> BulkCreateResponse:
    return await bulk_create_uc.execute(db, body)


@router.patch(
    "/bulk",
    response_model=BulkUpdateResponse,
    summary="Массово обновить источники",
)
async def bulk_update_sources(
    body: BulkUpdateRequest,
    db: AsyncSession = Depends(get_session),
) -> BulkUpdateResponse:
    return await bulk_update_uc.execute(db, body)


@router.post(
    "/import",
    response_model=BulkCreateResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Импорт источников из файла (JSON или CSV)",
)
async def import_sources(
    file: UploadFile = File(..., description="JSON-массив или CSV с полем url"),
    db: AsyncSession = Depends(get_session),
) -> BulkCreateResponse:
    return await import_uc.execute(db, file)


@router.get(
    "/export",
    summary="Экспорт источников (JSON или CSV)",
)
async def export_sources(
    fmt: str = Query("json", pattern="^(json|csv)$", description="Формат: json или csv"),
    status_filter: str | None = Query(None, alias="status"),
    platform: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> Response:
    return await export_uc.execute(
        db, fmt=fmt, status_filter=status_filter, platform_filter=platform
    )


# ── CRUD ───────────────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=SourceListResponse,
    summary="Список источников (поиск, фильтры, пагинация)",
)
async def list_sources(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    q: str | None = Query(None, description="Поиск по названию / ссылке"),
    status: str | None = Query(None),
    platform: str | None = Query(None),
    source_type: str | None = Query(None),
    owner_id: int | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> SourceListResponse:
    return await get_all_uc.execute(
        db,
        skip=skip,
        limit=limit,
        q=q,
        status=status,
        platform=platform,
        source_type=source_type,
        owner_id=owner_id,
    )


@router.post(
    "",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать источник",
)
async def create_source(
    body: SourceCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await post_uc.execute(db, body)


@router.get(
    "/{source_id}",
    response_model=SourceRead,
    summary="Получить источник по ID",
)
async def get_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await get_uc.execute(db, source_id)


@router.patch(
    "/{source_id}",
    response_model=SourceRead,
    summary="Обновить источник",
)
async def patch_source(
    source_id: int = Path(..., ge=1),
    body: SourceUpdateRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await patch_uc.execute(db, source_id, body)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить источник (soft delete)",
)
async def remove_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await delete_uc.execute(db, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Status transitions ─────────────────────────────────────────────────────


@router.post(
    "/{source_id}/enable",
    response_model=SourceRead,
    summary="Включить источник",
)
async def enable_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await enable_uc.execute(db, source_id)


@router.post(
    "/{source_id}/pause",
    response_model=SourceRead,
    summary="Поставить источник на паузу",
)
async def pause_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await pause_uc.execute(db, source_id)


@router.post(
    "/{source_id}/disable",
    response_model=SourceRead,
    summary="Отключить источник",
)
async def disable_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await disable_uc.execute(db, source_id)


@router.post(
    "/{source_id}/reset-error",
    response_model=SourceRead,
    summary="Сбросить статус ошибки",
)
async def reset_error_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await reset_error_uc.execute(db, source_id)


# ── Diagnostics & metadata ─────────────────────────────────────────────────


@router.post(
    "/{source_id}/validate",
    response_model=SourceValidateResponse,
    summary="Проверить доступность источника",
)
async def validate_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceValidateResponse:
    return await validate_uc.execute(db, source_id)


@router.post(
    "/{source_id}/refresh-metadata",
    response_model=SourceRefreshMetadataResponse,
    summary="Обновить метаданные источника из внешнего API",
)
async def refresh_metadata(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRefreshMetadataResponse:
    return await refresh_metadata_uc.execute(db, source_id)


@router.get(
    "/{source_id}/stats",
    response_model=SourceStats,
    summary="Статистика по источнику",
)
async def source_stats(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceStats:
    return await stats_uc.execute(db, source_id)


@router.get(
    "/{source_id}/health",
    response_model=SourceHealth,
    summary="Состояние (health) источника",
)
async def source_health(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceHealth:
    return await health_uc.execute(db, source_id)


# ── Sub-resources ──────────────────────────────────────────────────────────


@router.get(
    "/{source_id}/posts",
    summary="Публикации источника",
)
async def source_posts(
    source_id: int = Path(..., ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await source_posts_uc.execute(db, source_id, skip=skip, limit=limit)


@router.get(
    "/{source_id}/jobs",
    response_model=JobListResponse,
    summary="Задачи сбора по источнику (заглушка — планировщик не реализован)",
)
async def source_jobs(
    source_id: int = Path(..., ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
) -> JobListResponse:
    # No scheduler implemented yet — return empty list
    return JobListResponse(items=[], total=0)


@router.get(
    "/{source_id}/logs",
    response_model=AuditLogListResponse,
    summary="Журнал изменений источника",
)
async def source_logs(
    source_id: int = Path(..., ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> AuditLogListResponse:
    return await logs_uc.execute(db, source_id, skip=skip, limit=limit)


# ── Fetch / Collection job shortcuts ──────────────────────────────────────


@router.post(
    "/{source_id}/fetch",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить сбор по источнику (создаёт задачу manual_fetch)",
)
async def fetch_source(
    source_id: int = Path(..., ge=1),
    body: FetchRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.fetch_source(db, source_id, body, job_type=JobType.MANUAL_FETCH.value)


@router.post(
    "/{source_id}/fetch/history",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить исторический сбор (historical_fetch)",
)
async def fetch_source_history(
    source_id: int = Path(..., ge=1),
    body: HistoricalFetchRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.fetch_source_history(db, source_id, body)


@router.post(
    "/{source_id}/fetch/incremental",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить инкрементальный сбор (только новее last_success_at)",
)
async def fetch_source_incremental(
    source_id: int = Path(..., ge=1),
    body: FetchRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    return await jobs_uc.fetch_source(
        db, source_id, body, job_type=JobType.SCHEDULED_FETCH.value
    )
