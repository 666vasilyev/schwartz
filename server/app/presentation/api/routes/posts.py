"""
Posts API — GET /api/v1/posts
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.post import PostListResponse
from app.use_case.posts import get_all as get_all_uc

router = APIRouter(prefix="/api/v1/posts", tags=["Posts"])


@router.get(
    "",
    response_model=PostListResponse,
    summary="Список новостей с фильтрами по источнику, дате и категории СМИ",
)
async def list_posts(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=500),
    source_id: int | None = Query(None, ge=1, description="ID источника"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    db: AsyncSession = Depends(get_session),
) -> PostListResponse:
    return await get_all_uc.execute(
        db,
        skip=skip,
        limit=limit,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
    )
