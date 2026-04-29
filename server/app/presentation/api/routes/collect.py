"""
GET /collect — оркестрация: сервер вызывает collector, получает посты в ответе, пишет в БД.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.collect import CollectVkPublicResponse
from app.use_case.collect import get as collect_get

router = APIRouter(prefix="/collect", tags=["Collect"])


@router.get(
    "",
    response_model=CollectVkPublicResponse,
    summary="Сбор постов источника: collector → JSON → запись в БД на сервере",
)
async def collect_from_source(
    source_id: int = Query(..., description="ID источника в БД"),
    limit: int = Query(20, ge=1, le=100),
    use_mock: bool = Query(False),
    db: AsyncSession = Depends(get_session),
) -> CollectVkPublicResponse:
    return await collect_get.execute(db, source_id=source_id, limit=limit, use_mock=use_mock)
