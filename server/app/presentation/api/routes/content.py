"""
POST /analyze/source/{source_id} — посты стены источника: LLM по каждому; средние Шварца в БД.
GET  /analyze/source/{source_id}/stored — последний сохранённый агрегат Шварца из БД.
"""
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.post import get_post_by_id
from app.presentation.api.dependencies import get_session
from app.presentation.schemas.analysis import (
    LemmaAnalysisResult,
    LemmaTextRequest,
    SourceAnalyzeResponse,
    SourceStoredSchwartzResponse,
)
from app.use_case.analyze import get_stored as analyze_get_stored
from app.use_case.analyze import lemma as analyze_lemma
from app.use_case.analyze import post as analyze_post

router = APIRouter(prefix="/analyze", tags=["Content Analysis"])


@router.post(
    "/lemma",
    response_model=LemmaAnalysisResult,
    summary="Анализ текста по словарному методу (lemma_coefficients_RUS.csv)",
    description=(
        "Без вызова LLM. Ищет в тексте леммы из CSV-словаря, суммирует их веса "
        "по 10 измерениям ценностной картины мира (модель Шварца в русской разметке), "
        "нормирует результат (max → 1.0)."
    ),
)
def analyze_text_lemma(body: LemmaTextRequest) -> LemmaAnalysisResult:
    return analyze_lemma.execute(body.text)


@router.get(
    "/lemma/{post_id}",
    response_model=LemmaAnalysisResult,
    summary="Анализ поста по словарному методу (lemma_coefficients_RUS.csv)",
)
async def analyze_post_lemma(
    post_id: int,
    db: AsyncSession = Depends(get_session),
) -> LemmaAnalysisResult:
    post = await get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")
    if not post.text or not post.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Текст поста пуст")
    return analyze_lemma.execute(post.text)


@router.get(
    "/llm/{source_id}/stored",
    response_model=SourceStoredSchwartzResponse,
    summary="Сохранённый анализ Шварца по источнику (только чтение из БД)",
)
async def get_stored_source_schwartz(
    source_id: int,
    db: AsyncSession = Depends(get_session),
) -> SourceStoredSchwartzResponse:
    return await analyze_get_stored.execute(db, source_id)


@router.post(
    "/llm/{source_id}",
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
