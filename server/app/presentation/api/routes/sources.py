"""
GET /sources — список; GET /sources/{id}; POST /sources — ссылка на паблик → запись в БД.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.source import (
    SourceCreateRequest,
    SourceListResponse,
    SourceRead,
    SourceUpdateRequest,
)
from app.use_case.sources import delete as delete_uc
from app.use_case.sources import get as get_uc
from app.use_case.sources import get_all as get_all_uc
from app.use_case.sources import patch as patch_uc
from app.use_case.sources import post as post_uc

router = APIRouter(prefix="/sources", tags=["Sources"])


@router.get(
    "",
    response_model=SourceListResponse,
    summary="Список источников (поиск по названию/ссылке, пагинация)",
)
async def list_sources(
    skip: int = Query(0, ge=0, description="Смещение (0-based)"),
    limit: int = Query(9, ge=1, le=500, description="Размер страницы"),
    q: str | None = Query(None, description="Поиск по подстроке в названии и ссылке"),
    db: AsyncSession = Depends(get_session),
) -> SourceListResponse:
    return await get_all_uc.execute(db, skip=skip, limit=limit, q=q)


@router.post(
    "",
    response_model=SourceRead,
    status_code=status.HTTP_201_CREATED,
    summary="Добавить источник по ссылке на паблик VK",
)
async def create_source(
    body: SourceCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await post_uc.execute(db, body)


@router.get(
    "/{source_id}",
    response_model=SourceRead,
    summary="Источник по id",
)
async def get_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await get_uc.execute(db, source_id)


@router.patch(
    "/{source_id}",
    response_model=SourceRead,
    summary="Частично обновить источник",
)
async def patch_source(
    source_id: int,
    body: SourceUpdateRequest,
    db: AsyncSession = Depends(get_session),
) -> SourceRead:
    return await patch_uc.execute(db, source_id, body)


@router.delete(
    "/{source_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить источник",
)
async def remove_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await delete_uc.execute(db, source_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
