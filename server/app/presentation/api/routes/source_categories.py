"""
Source Categories API — /api/v1/source-categories
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.source_category import (
    SourceCategoryCreateRequest,
    SourceCategoryListResponse,
    SourceCategoryRead,
    SourceCategoryUpdateRequest,
)
from app.use_case.sources import categories as categories_uc

router = APIRouter(prefix="/api/v1/source-categories", tags=["Source Categories"])


@router.post(
    "",
    response_model=SourceCategoryRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать категорию источника",
)
async def create_category(
    body: SourceCategoryCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> SourceCategoryRead:
    return await categories_uc.create(db, body)


@router.get(
    "",
    response_model=SourceCategoryListResponse,
    summary="Список категорий источников",
)
async def list_categories(
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
) -> SourceCategoryListResponse:
    return await categories_uc.list_all(db, skip=skip, limit=limit)


@router.get(
    "/{category_id}",
    response_model=SourceCategoryRead,
    summary="Категория по ID",
)
async def get_category(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> SourceCategoryRead:
    return await categories_uc.get_by_id(db, category_id)


@router.patch(
    "/{category_id}",
    response_model=SourceCategoryRead,
    summary="Обновить категорию",
)
async def patch_category(
    category_id: int = Path(..., ge=1),
    body: SourceCategoryUpdateRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> SourceCategoryRead:
    return await categories_uc.patch(db, category_id, body)


@router.delete(
    "/{category_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить категорию",
)
async def delete_category(
    category_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await categories_uc.delete(db, category_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
