"""
VK Integration API — /api/v1/vk
10 endpoints:
  POST  /resolve
  POST  /validate
  GET   /sources/{id}/metadata
  POST  /sources/{id}/metadata/refresh
  POST  /sources/{id}/fetch
  POST  /sources/{id}/fetch/history
  POST  /sources/{id}/fetch/preview
  GET   /sources/{id}/state
  POST  /sources/{id}/state/reset
  GET   /tokens
  POST  /tokens
  POST  /tokens/check
  POST  /tokens/{token_id}/rotate
  PATCH /tokens/{token_id}/activate
  PATCH /tokens/{token_id}/deactivate
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.vk import (
    VkCollectionState,
    VkFetchPreviewRequest,
    VkFetchPreviewResponse,
    VkFetchRequest,
    VkFetchResult,
    VkGroupMetadata,
    VkHistoricalFetchRequest,
    VkMetadataRefreshResponse,
    VkResolveRequest,
    VkResolvedSource,
    VkStateResetResponse,
    VkTokenAddRequest,
    VkTokenCheckRequest,
    VkTokenCheckResponse,
    VkTokenListResponse,
    VkTokenRead,
    VkTokenRotateResponse,
    VkValidateRequest,
    VkValidateResponse,
)
from app.use_case.vk import fetch as fetch_uc
from app.use_case.vk import metadata as metadata_uc
from app.use_case.vk import resolve as resolve_uc
from app.use_case.vk import state as state_uc
from app.use_case.vk import tokens as tokens_uc
from app.use_case.vk import validate as validate_uc

router = APIRouter(prefix="/api/v1/vk", tags=["VK"])


# ── Resolve & validate ─────────────────────────────────────────────────────


@router.post(
    "/resolve",
    response_model=VkResolvedSource,
    summary="Разрешить VK URL в метаданные группы",
)
async def resolve_vk(body: VkResolveRequest) -> VkResolvedSource:
    return await resolve_uc.execute(body)


@router.post(
    "/validate",
    response_model=VkValidateResponse,
    summary="Проверить доступность VK группы по owner_id",
)
async def validate_vk(body: VkValidateRequest) -> VkValidateResponse:
    return await validate_uc.execute(body)


# ── Metadata ───────────────────────────────────────────────────────────────


@router.get(
    "/sources/{source_id}/metadata",
    response_model=VkGroupMetadata,
    summary="Метаданные VK группы из БД",
)
async def get_metadata(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> VkGroupMetadata:
    return await metadata_uc.get_metadata(db, source_id)


@router.post(
    "/sources/{source_id}/metadata/refresh",
    response_model=VkMetadataRefreshResponse,
    summary="Обновить метаданные VK группы из API",
)
async def refresh_metadata(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> VkMetadataRefreshResponse:
    return await metadata_uc.refresh_metadata(db, source_id)


# ── Fetch ──────────────────────────────────────────────────────────────────


@router.post(
    "/sources/{source_id}/fetch",
    response_model=VkFetchResult,
    status_code=status.HTTP_201_CREATED,
    summary="Инкрементальный сбор (с позиции last_vk_post_id)",
)
async def fetch_vk(
    source_id: int = Path(..., ge=1),
    body: VkFetchRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> VkFetchResult:
    return await fetch_uc.fetch(db, source_id, body)


@router.post(
    "/sources/{source_id}/fetch/history",
    response_model=VkFetchResult,
    status_code=status.HTTP_201_CREATED,
    summary="Исторический сбор за период",
)
async def fetch_vk_history(
    source_id: int = Path(..., ge=1),
    body: VkHistoricalFetchRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> VkFetchResult:
    return await fetch_uc.fetch_historical(db, source_id, body)


@router.post(
    "/sources/{source_id}/fetch/preview",
    response_model=VkFetchPreviewResponse,
    summary="Предпросмотр постов без сохранения в БД",
)
async def fetch_vk_preview(
    source_id: int = Path(..., ge=1),
    body: VkFetchPreviewRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> VkFetchPreviewResponse:
    return await fetch_uc.fetch_preview(db, source_id, body)


# ── Collection state ───────────────────────────────────────────────────────


@router.get(
    "/sources/{source_id}/state",
    response_model=VkCollectionState,
    summary="Состояние сбора (курсор, счётчики)",
)
async def get_state(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> VkCollectionState:
    return await state_uc.get_state(db, source_id)


@router.post(
    "/sources/{source_id}/state/reset",
    response_model=VkStateResetResponse,
    summary="Сбросить курсор сбора (last_vk_post_id, total_collected)",
)
async def reset_state(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> VkStateResetResponse:
    return await state_uc.reset_state(db, source_id)


# ── Token management ───────────────────────────────────────────────────────


@router.get(
    "/tokens",
    response_model=VkTokenListResponse,
    summary="Список VK токенов",
)
async def list_tokens(db: AsyncSession = Depends(get_session)) -> VkTokenListResponse:
    return await tokens_uc.get_list(db)


@router.post(
    "/tokens",
    response_model=VkTokenRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить VK токен",
)
async def add_token(
    body: VkTokenAddRequest,
    db: AsyncSession = Depends(get_session),
) -> VkTokenRead:
    return await tokens_uc.add(db, body)


@router.post(
    "/tokens/check",
    response_model=VkTokenCheckResponse,
    summary="Проверить VK токен через users.get",
)
async def check_token(body: VkTokenCheckRequest) -> VkTokenCheckResponse:
    return await tokens_uc.check(body)


@router.post(
    "/tokens/{token_id}/rotate",
    response_model=VkTokenRotateResponse,
    summary="Заменить токен: деактивировать старый, добавить новый",
)
async def rotate_token(
    token_id: int = Path(..., ge=1),
    body: VkTokenAddRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> VkTokenRotateResponse:
    return await tokens_uc.rotate(db, token_id, body)


@router.patch(
    "/tokens/{token_id}/activate",
    response_model=VkTokenRead,
    summary="Активировать токен",
)
async def activate_token(
    token_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> VkTokenRead:
    return await tokens_uc.toggle_active(db, token_id, active=True)


@router.patch(
    "/tokens/{token_id}/deactivate",
    response_model=VkTokenRead,
    summary="Деактивировать токен",
)
async def deactivate_token(
    token_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> VkTokenRead:
    return await tokens_uc.toggle_active(db, token_id, active=False)
