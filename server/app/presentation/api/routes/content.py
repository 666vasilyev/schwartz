"""
POST /analyze/source/{source_id} — посты стены источника: LLM по каждому; средние Шварца в БД.
GET  /analyze/source/{source_id}/stored — последний сохранённый агрегат Шварца из БД.
"""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang, read_baseline
from app.infrastructure.repositories.post import get_post_by_id
from app.presentation.api.dependencies import get_session
from app.presentation.schemas.analysis import (
    CategoryLemmaByDayResponse,
    LemmaAnalysisResult,
    LemmaBaselineResponse,
    LemmaCategoriesRequest,
    LemmaSourcesRequest,
    LemmaTextRequest,
    LLMOverrideRequest,
    SourceAnalyzeResponse,
    SourceLemmaAnalysisResponse,
    SourceStoredSchwartzResponse,
)
from app.use_case.analyze import get_stored as analyze_get_stored
from app.use_case.analyze import lemma as analyze_lemma
from app.use_case.analyze import lemma_categories as analyze_lemma_categories
from app.use_case.analyze import lemma_category as analyze_lemma_category
from app.use_case.analyze import lemma_category_by_day as analyze_lemma_category_by_day
from app.use_case.analyze import lemma_source as analyze_lemma_source
from app.use_case.analyze import post as analyze_post

router = APIRouter(prefix="/analyze", tags=["Content Analysis"])


@router.get(
    "/lemma/baseline",
    response_model=LemmaBaselineResponse,
    summary="Базовое распределение ЦКМ для языка (эталонные значения из словаря)",
)
def get_lemma_baseline(
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
) -> LemmaBaselineResponse:
    result = read_baseline(lang)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Baseline для языка '{lang.value}' не найден")
    return LemmaBaselineResponse(**result)


@router.post(
    "/lemma",
    response_model=LemmaAnalysisResult,
    summary="Анализ текста по словарному методу",
)
def analyze_text_lemma(
    body: LemmaTextRequest,
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
) -> LemmaAnalysisResult:
    return analyze_lemma.execute(body.text, lang)


@router.get(
    "/lemma/post/{post_id}",
    response_model=LemmaAnalysisResult,
    summary="ЦКМ поста по словарному методу",
)
async def analyze_post_lemma(
    post_id: int,
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
    db: AsyncSession = Depends(get_session),
) -> LemmaAnalysisResult:
    post = await get_post_by_id(db, post_id)
    if post is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пост не найден")
    if not post.text or not post.text.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="Текст поста пуст")
    return analyze_lemma.execute(post.text, lang)


@router.post(
    "/lemma/source",
    response_model=list[SourceLemmaAnalysisResponse],
    summary="ЦКМ по списку источников (словарный метод, один результат на источник)",
)
async def analyze_source_lemma(
    body: LemmaSourcesRequest,
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
    limit: int | None = Query(None, ge=1, description="Последние N постов (по дате публикации)"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    db: AsyncSession = Depends(get_session),
) -> list[SourceLemmaAnalysisResponse]:
    return await analyze_lemma_source.execute(
        db, body.source_ids, lang=lang, limit=limit, date_from=date_from, date_to=date_to
    )


@router.post(
    "/lemma/categories",
    response_model=list[SourceLemmaAnalysisResponse],
    summary="ЦКМ по списку категорий (словарный метод, один результат на категорию)",
)
async def analyze_categories_lemma(
    body: LemmaCategoriesRequest,
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
    limit: int | None = Query(None, ge=1, description="Последние N постов на категорию (по дате публикации)"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    db: AsyncSession = Depends(get_session),
) -> list[SourceLemmaAnalysisResponse]:
    return await analyze_lemma_categories.execute(
        db, body.category_names, lang=lang, limit=limit, date_from=date_from, date_to=date_to
    )


@router.get(
    "/lemma/category/{category_name}",
    response_model=SourceLemmaAnalysisResponse,
    summary="ЦКМ категории источников по словарному методу (агрегат по постам)",
)
async def analyze_category_lemma(
    category_name: str,
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
    limit: int | None = Query(None, ge=1, description="Последние N постов (по дате публикации)"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    db: AsyncSession = Depends(get_session),
) -> SourceLemmaAnalysisResponse:
    return await analyze_lemma_category.execute(
        db, category_name, lang=lang, limit=limit, date_from=date_from, date_to=date_to
    )


@router.get(
    "/lemma/category/{category_name}/by_day",
    response_model=CategoryLemmaByDayResponse,
    summary="ЦКМ категории по словарному методу, в разбивке по дням публикации постов",
)
async def analyze_category_lemma_by_day(
    category_name: str,
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, eng, de"),
    limit: int | None = Query(None, ge=1, description="Последние N постов категории (по дате публикации)"),
    date_from: datetime | None = Query(None, description="Начало диапазона (published_at >=)"),
    date_to: datetime | None = Query(None, description="Конец диапазона (published_at <=)"),
    db: AsyncSession = Depends(get_session),
) -> CategoryLemmaByDayResponse:
    return await analyze_lemma_category_by_day.execute(
        db, category_name, lang=lang, limit=limit, date_from=date_from, date_to=date_to
    )


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
    body: LLMOverrideRequest = Body(default_factory=LLMOverrideRequest),
    db: AsyncSession = Depends(get_session),
) -> SourceAnalyzeResponse:
    """
    VK: посты с `posts.owner_id == sources.vk_owner_id`. RSS: посты с `posts.source_id`.
    Для каждого с непустым текстом — LLM (деструктивность + Шварц). Средние записываются
    в `source_schwartz_analysis` (одна строка на источник, перезапись при каждом вызове).

    Тело запроса опционально. Передайте `provider` и/или `model` чтобы переопределить
    активный LLM для этого конкретного вызова.
    """
    return await analyze_post.execute(
        db, source_id, limit=limit, provider=body.provider, model=body.model
    )
