"""
Posts API — /api/v1/posts
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, File, Query, Response, UploadFile
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.post import PostListResponse
from app.use_case.posts import export_posts as export_uc
from app.use_case.posts import get_all as get_all_uc
from app.use_case.posts import import_posts as import_uc

router = APIRouter(prefix="/api/v1/posts", tags=["Posts"])


@router.get(
    "/export",
    summary="Экспорт новостей (JSON или CSV)",
)
async def export_posts(
    fmt: str = Query("json", pattern="^(json|csv)$", description="Формат: json или csv"),
    source_id: int | None = Query(None, ge=1, description="Фильтр по источнику"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    q: str | None = Query(None, description="Поиск подстроки в тексте"),
    db: AsyncSession = Depends(get_session),
) -> Response:
    return await export_uc.execute(
        db,
        fmt=fmt,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        search=q,
    )


@router.post(
    "/import",
    summary="Импорт новостей из файла (JSON или CSV)",
)
async def import_posts(
    file: UploadFile = File(..., description="JSON-массив или CSV с полями поста"),
    db: AsyncSession = Depends(get_session),
) -> dict:
    return await import_uc.execute(db, file)


@router.get(
    "",
    response_model=PostListResponse,
    summary="Список новостей с фильтрами",
)
async def list_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    q: str | None = Query(None, description="Поиск подстроки в тексте поста"),
    source_id: int | None = Query(None, ge=1, description="ID источника"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    db: AsyncSession = Depends(get_session),
) -> PostListResponse:
    return await get_all_uc.execute(
        db,
        skip=skip,
        limit=limit,
        search=q,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
    )
