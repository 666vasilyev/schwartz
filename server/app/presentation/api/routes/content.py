"""
POST /analyze/source/{source_id} — посты стены источника: LLM по каждому; средние Шварца в БД.
GET  /analyze/source/{source_id}/stored — последний сохранённый агрегат Шварца из БД.
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.analysis import SourceAnalyzeResponse, SourceStoredSchwartzResponse
from app.use_case.analyze import get_stored as analyze_get_stored
from app.use_case.analyze import post as analyze_post

router = APIRouter(prefix="/analyze", tags=["Content Analysis"])


@router.get(
    "/source/{source_id}/stored",
    response_model=SourceStoredSchwartzResponse,
    summary="Сохранённый анализ Шварца по источнику (только чтение из БД)",
)
async def get_stored_source_schwartz(
    source_id: int,
    db: AsyncSession = Depends(get_session),
) -> SourceStoredSchwartzResponse:
    return await analyze_get_stored.execute(db, source_id)


@router.post(
    "/source/{source_id}",
    response_model=SourceAnalyzeResponse,
    summary="Проанализировать посты источника (агрегат Шварца сохраняется в БД)",
)
async def analyze_source(
    source_id: int,
    limit: int | None = Query(
        None,
        ge=1,
        le=2000,
        description="Ограничить число постов в порядке id (сначала старые)",
    ),
    db: AsyncSession = Depends(get_session),
) -> SourceAnalyzeResponse:
    """
    VK: посты с `posts.owner_id == sources.vk_owner_id`. RSS: посты с `posts.source_id`.
    Для каждого с непустым текстом — LLM (деструктивность + Шварц). Средние записываются
    в `source_schwartz_analysis` (одна строка на источник, перезапись при каждом вызове).
    """
    return await analyze_post.execute(db, source_id, limit=limit)
