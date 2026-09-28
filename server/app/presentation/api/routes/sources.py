"""
Sources management API — /api/v1/sources
"""
from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, File, HTTPException, Path, Query, Response, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_current_user, get_session
from app.presentation.schemas.source import (
    AuditLogListResponse,
    BulkCreateRequest,
    BulkCreateResponse,
    BulkUpdateRequest,
    BulkUpdateResponse,
    JobListResponse,
    SourceActionRequest,
    SourceActionResponse,
    SourceCreateRequest,
    SourceHealth,
    SourceListResponse,
    SourceRead,
    SourceRefreshMetadataResponse,
    SourceStats,
    SourceUpdateRequest,
    SourceValidateResponse,
)
from app.use_case.sources import action as action_uc
from app.use_case.sources import delete as delete_uc
from app.use_case.sources import export_sources as export_uc
from app.use_case.sources import get as get_uc
from app.use_case.sources import get_all as get_all_uc
from app.use_case.sources import get_image as get_image_uc
from app.use_case.sources import upload_image as upload_image_uc
from app.use_case.sources import delete_image as delete_image_uc
from app.use_case.sources import health as health_uc
from app.use_case.sources import import_sources as import_uc
from app.use_case.sources import logs as logs_uc
from app.use_case.sources import patch as patch_uc
from app.use_case.sources import post as post_uc
from app.use_case.sources import refresh_metadata as refresh_metadata_uc
from app.use_case.sources import source_posts as source_posts_uc
from app.use_case.sources import stats as stats_uc
from app.use_case.sources import validate as validate_uc
from app.use_case.sources import bulk_create as bulk_create_uc
from app.use_case.sources import bulk_update as bulk_update_uc

router = APIRouter(prefix="/api/v1/sources", tags=["Sources"], dependencies=[Depends(get_current_user)])


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
    db: AsyncSession = Depends(get_session),
) -> Response:
    return await export_uc.execute(
        db, fmt=fmt, status_filter=status_filter
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
    source_type: str | None = Query(None),
    owner_id: int | None = Query(None),
    sort_by: Literal["name", "source_type", "status"] | None = Query(
        None,
        description=(
            "Поле сортировки. name — алфавитный порядок (см. sort_dir). "
            "source_type / status — источники со значением sort_value поднимаются "
            "наверх, остальные — ниже (порядок между ними не гарантирован)."
        ),
    ),
    sort_dir: Literal["asc", "desc"] = Query(
        "asc",
        description=(
            "Направление сортировки. Для name — обычный алфавит (asc) / обратный (desc). "
            "Для source_type/status — asc поднимает sort_value наверх, desc опускает его вниз."
        ),
    ),
    sort_value: str | None = Query(
        None,
        description=(
            "Значение, которое нужно поднять наверх при sort_by=source_type "
            "(rss / vk / telegram) или sort_by=status (active / paused / disabled / "
            "error / blocked / deleted). Обязателен при этих sort_by."
        ),
    ),
    db: AsyncSession = Depends(get_session),
) -> SourceListResponse:
    if sort_by in ("source_type", "status") and not sort_value:
        raise HTTPException(
            status_code=422,
            detail=f"sort_value обязателен при sort_by='{sort_by}'",
        )
    return await get_all_uc.execute(
        db,
        skip=skip,
        limit=limit,
        q=q,
        status=status,
        source_type=source_type,
        owner_id=owner_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        sort_value=sort_value,
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


# ── Изображение источника ───────────────────────────────────────────────────
# Отдельные эндпоинты, а не поле в POST/PATCH: тело создания сейчас JSON
# (multipart потребовал бы переписывать все поля SourceCreateRequest на
# Form(...)), да и это тот же паттерн, что аватар/лого у любого ресурса —
# сначала создаём источник, потом (сразу же или позже) заливаем картинку.


@router.post(
    "/{source_id}/image",
    response_model=SourceRead,
    summary="Загрузить/заменить изображение источника",
)
async def upload_source_image(
    source_id: int = Path(..., ge=1),
    file: UploadFile = File(..., description="JPEG/PNG/WEBP/GIF, до 5 МБ"),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await upload_image_uc.execute(db, source_id, file)


@router.delete(
    "/{source_id}/image",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить изображение источника",
)
async def remove_source_image(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await delete_image_uc.execute(db, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get(
    "/{source_id}/image",
    summary="Отдать файл изображения источника",
)
async def get_source_image(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> FileResponse:
    path = await get_image_uc.execute(db, source_id)
    return FileResponse(path)


# ── Unified action endpoint ────────────────────────────────────────────────


@router.post(
    "/{source_id}/action",
    response_model=SourceActionResponse,
    summary=(
        "Действие над источником: "
        "enable | disable | pause | reset_error | fetch | fetch_history | fetch_incremental"
    ),
)
async def source_action(
    source_id: int = Path(..., ge=1),
    body: SourceActionRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> SourceActionResponse:
    return await action_uc.execute(db, source_id, body)


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
    summary="Задачи сбора по источнику",
)
async def source_jobs(
    source_id: int = Path(..., ge=1),
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=100),
    db: AsyncSession = Depends(get_session),
) -> JobListResponse:
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
