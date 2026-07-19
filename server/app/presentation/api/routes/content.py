"""
POST /analyze/source/{source_id} — посты стены источника: LLM по каждому; средние Шварца в БД.
GET  /analyze/source/{source_id}/stored — последний сохранённый агрегат Шварца из БД.
"""
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content import lemma_scorer
from app.application.services.content.lemma_llm_extractor import extract_new_lemmas
from app.application.services.content.lemma_scorer import LemmaLang, read_baseline
from app.infrastructure.repositories.post import get_post_by_id
from app.presentation.api.dependencies import get_session
from app.infrastructure.clients.llm import ask_llm
from app.presentation.schemas.analysis import (
    CategoriesLemmaCkmResponse,
    CategoriesSchwartzTimeseriesResponse,
    CategoryLemmaByDayResponse,
    CategoryLangItem,
    LemmaAnalysisResult,
    LemmaAppendRequest,
    LemmaAppendResponse,
    LemmaBaselineResponse,
    LemmaBlacklistActionRequest,
    LemmaBlacklistActionResponse,
    LemmaBlacklistListResponse,
    LemmaCategoriesRequest,
    LemmaExtractRequest,
    LemmaExtractResponse,
    LemmaListResponse,
    LemmaParameterCountsResponse,
    LemmaSourcesRequest,
    LemmaTextRequest,
    LemmaTrendCandidatesResponse,
    LLMChatRequest,
    LLMChatResponse,
    LLMOverrideRequest,
    NewLemmaItem,
    SourceAnalyzeResponse,
    SourceLemmaAnalysisResponse,
    SourceStoredSchwartzResponse,
    TimeGranularity,
)
from app.use_case.analyze import get_stored as analyze_get_stored
from app.use_case.analyze import lemma as analyze_lemma
from app.use_case.analyze import lemma_categories as analyze_lemma_categories
from app.use_case.analyze import lemma_categories_by_day as analyze_lemma_categories_by_day
from app.use_case.analyze import lemma_categories_combined as analyze_lemma_categories_combined
from app.use_case.analyze import lemma_category as analyze_lemma_category
from app.use_case.analyze import lemma_category_by_day as analyze_lemma_category_by_day
from app.use_case.analyze import lemma_source as analyze_lemma_source
from app.use_case.analyze import lemma_trend_candidates as analyze_lemma_trend_candidates
from app.use_case.analyze import lemma_trend_weight as analyze_lemma_trend_weight
from app.use_case.analyze import post as analyze_post

router = APIRouter(prefix="/analyze", tags=["Content Analysis"])

# ── Общие Query-параметры (переиспользуются в нескольких ручках ниже, чтобы не
#    держать одинаковый Query(...)/описание в 7 и 5 местах соответственно) ──
_LANG_QUERY = Query(LemmaLang.ru, description="Язык словаря: ru, ru_un, usa, usa_un, frg")
_DATE_FROM_QUERY = Query(None, description="Начало диапазона (published_at >=)")
_DATE_TO_QUERY = Query(None, description="Конец диапазона (published_at <=)")


@router.get(
    "/lemma/baseline",
    response_model=LemmaBaselineResponse,
    summary="Базовое распределение ЦКМ для языка (эталонные значения из словаря)",
)
def get_lemma_baseline(
    lang: LemmaLang = _LANG_QUERY,
) -> LemmaBaselineResponse:
    result = read_baseline(lang)
    if result is None:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"Baseline для языка '{lang.value}' не найден")
    return LemmaBaselineResponse(**result)


@router.get(
    "/lemma/counts",
    response_model=LemmaParameterCountsResponse,
    summary="Только количество лемм словаря по каждому из 10 параметров ЦКМ",
)
def get_lemma_counts(
    lang: LemmaLang = Query(LemmaLang.ru, description="Язык словаря: ru, ru_un, ru_merged, usa, usa_un, usa_merged, frg"),
) -> LemmaParameterCountsResponse:
    return LemmaParameterCountsResponse(lang=lang, counts=lemma_scorer.count_lemmas_by_parameter(lang))


@router.post(
    "/lemma",
    response_model=LemmaAnalysisResult,
    summary="Анализ текста по словарному методу",
)
def analyze_text_lemma(
    body: LemmaTextRequest,
    lang: LemmaLang = _LANG_QUERY,
) -> LemmaAnalysisResult:
    return analyze_lemma.execute(body.text, lang)


@router.get(
    "/lemma/post/{post_id}",
    response_model=LemmaAnalysisResult,
    summary="ЦКМ поста по словарному методу",
)
async def analyze_post_lemma(
    post_id: int,
    lang: LemmaLang = _LANG_QUERY,
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
    lang: LemmaLang = _LANG_QUERY,
    limit: int | None = Query(None, ge=1, description="Последние N постов (по дате публикации)"),
    date_from: datetime | None = _DATE_FROM_QUERY,
    date_to: datetime | None = _DATE_TO_QUERY,
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
    limit: int | None = Query(None, ge=1, description="Последние N постов на категорию (по дате публикации)"),
    date_from: datetime | None = _DATE_FROM_QUERY,
    date_to: datetime | None = _DATE_TO_QUERY,
    db: AsyncSession = Depends(get_session),
) -> list[SourceLemmaAnalysisResponse]:
    categories = [(item.category_name, item.lang) for item in body.categories]
    return await analyze_lemma_categories.execute(
        db, categories, limit=limit, date_from=date_from, date_to=date_to
    )


@router.post(
    "/lemma/categories/combined",
    response_model=CategoriesLemmaCkmResponse,
    summary="ЦКМ по объединённому результату нескольких категорий (один результат) с леммами по каждому параметру",
)
async def analyze_categories_lemma_combined(
    body: LemmaCategoriesRequest,
    top_n_lemmas: int = Query(
        15, ge=1, le=100, description="Сколько лемм максимум показывать на параметр (по убыванию частоты)"
    ),
    limit: int | None = Query(
        None, ge=1, description="Последние N постов НА КАЖДУЮ категорию (по дате публикации)"
    ),
    date_from: datetime | None = _DATE_FROM_QUERY,
    date_to: datetime | None = _DATE_TO_QUERY,
    db: AsyncSession = Depends(get_session),
) -> CategoriesLemmaCkmResponse:
    """
    Тело — как у /lemma/categories: список пар {category_name, lang}, у каждой
    категории свой язык словаря. В отличие от /lemma/categories (список
    результатов, по одному на категорию) здесь один комбинированный результат:
    все посты всех категорий (каждая — своим словарём) объединяются в единый
    агрегат с разбивкой по леммам на параметр.
    """
    categories = [(item.category_name, item.lang) for item in body.categories]
    return await analyze_lemma_categories_combined.execute(
        db,
        categories,
        top_n_lemmas=top_n_lemmas,
        limit=limit,
        date_from=date_from,
        date_to=date_to,
    )


@router.post(
    "/lemma/categories/granularity/{granularity}",
    response_model=CategoriesSchwartzTimeseriesResponse,
    summary="Временны́е ряды ЦКМ по нескольким категориям: data[параметр][категория] = [значения по периодам]",
)
async def analyze_categories_lemma_by_day(
    granularity: TimeGranularity,
    body: LemmaCategoriesRequest,
    date_from: datetime = Query(..., description="Начало диапазона (включительно), принимает дату или datetime"),
    date_to: datetime = Query(..., description="Конец диапазона (включительно), принимает дату или datetime"),
    db: AsyncSession = Depends(get_session),
) -> CategoriesSchwartzTimeseriesResponse:
    df = date_from.date() if isinstance(date_from, datetime) else date_from
    dt_ = date_to.date() if isinstance(date_to, datetime) else date_to
    if dt_ < df:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="date_to не может быть раньше date_from",
        )
    categories = [(item.category_name, item.lang) for item in body.categories]
    return await analyze_lemma_categories_by_day.execute(
        db, categories, date_from=df, date_to=dt_, granularity=granularity
    )


@router.get(
    "/lemma/category/{category_name}",
    response_model=SourceLemmaAnalysisResponse,
    summary="ЦКМ категории источников по словарному методу (агрегат по постам)",
)
async def analyze_category_lemma(
    category_name: str,
    lang: LemmaLang = _LANG_QUERY,
    limit: int | None = Query(None, ge=1, description="Последние N постов (по дате публикации)"),
    date_from: datetime | None = _DATE_FROM_QUERY,
    date_to: datetime | None = _DATE_TO_QUERY,
    db: AsyncSession = Depends(get_session),
) -> SourceLemmaAnalysisResponse:
    return await analyze_lemma_category.execute(
        db, category_name, lang=lang, limit=limit, date_from=date_from, date_to=date_to
    )


@router.get(
    "/lemma/category/{category_name}/granularity/{granularity}",
    response_model=CategoryLemmaByDayResponse,
    summary="ЦКМ категории по словарному методу, в разбивке по периодам (день / неделя / месяц)",
)
async def analyze_category_lemma_by_day(
    category_name: str,
    granularity: TimeGranularity,
    lang: LemmaLang = _LANG_QUERY,
    limit: int | None = Query(None, ge=1, description="Последние N постов категории (по дате публикации)"),
    date_from: datetime | None = _DATE_FROM_QUERY,
    date_to: datetime | None = _DATE_TO_QUERY,
    db: AsyncSession = Depends(get_session),
) -> CategoryLemmaByDayResponse:
    return await analyze_lemma_category_by_day.execute(
        db, category_name, lang=lang, granularity=granularity,
        limit=limit, date_from=date_from, date_to=date_to,
    )


@router.post(
    "/lemma/extract",
    response_model=LemmaExtractResponse,
    summary="LLM предлагает до 10 новых лемм для словаря по тексту (ничего не сохраняет)",
)
async def extract_lemma_candidates(
    body: LemmaExtractRequest,
    lang: LemmaLang = Query(
        LemmaLang.ru, description="Словарь, с которым сверяем дубли: ru, ru_un, usa, usa_un, frg"
    ),
) -> LemmaExtractResponse:
    """
    Прогоняет текст через словарный метод (чтобы узнать, какие леммы `lang` уже
    встретились), затем просит LLM подобрать новые, не повторяющиеся леммы по тем
    же 10 измерениям ЦКМ. Результат — превью для ручной проверки; чтобы сохранить
    леммы в CSV, передайте `new_lemmas` из ответа в `/analyze/lemma/append`.
    """
    new_lemmas, matched = await extract_new_lemmas(
        body.text, lang, count=body.count, provider=body.provider, model=body.model
    )
    return LemmaExtractResponse(
        lang=lang,
        already_matched=matched,
        lemmas=[NewLemmaItem(**item) for item in new_lemmas],
    )


def _append_lemmas_to_csv(body: LemmaAppendRequest, lang: LemmaLang) -> LemmaAppendResponse:
    """Общая логика для /lemma/append и /lemma/csv (POST) — upsert в CSV-словарь."""
    try:
        added, updated, skipped = lemma_scorer.append_lemmas(
            lang, [item.model_dump() for item in body.lemmas]
        )
    except lemma_scorer.MergedLangNotWritableError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return LemmaAppendResponse(lang=lang, added=added, updated=updated, skipped_duplicates=skipped)


@router.post(
    "/lemma/append",
    response_model=LemmaAppendResponse,
    summary="Добавить новые / обновить существующие леммы в CSV-словаре",
)
def append_lemma_candidates(
    body: LemmaAppendRequest,
    lang: LemmaLang = Query(
        ..., description="Словарь для записи: ru, ru_un, usa, usa_un, frg (merged — вычисляемые, только для чтения)"
    ),
) -> LemmaAppendResponse:
    return _append_lemmas_to_csv(body, lang)


@router.get(
    "/lemma/csv",
    response_model=LemmaListResponse,
    summary="Просмотреть текущее содержимое CSV-словаря",
)
def list_lemma_csv(
    lang: LemmaLang = Query(
        ..., description="Словарь: ru, ru_un, ru_merged, usa, usa_un, usa_merged, frg"
    ),
    search: str | None = Query(None, description="Подстрока для фильтра по лемме (регистронезависимо)"),
    limit: int = Query(100, ge=1, le=1000, description="Сколько строк вернуть за один запрос"),
    offset: int = Query(0, ge=0, description="Сколько строк пропустить (пагинация)"),
) -> LemmaListResponse:
    rows, total = lemma_scorer.list_lemmas(lang, search=search, limit=limit, offset=offset)
    return LemmaListResponse(
        lang=lang,
        total=total,
        offset=offset,
        limit=limit,
        lemmas=[NewLemmaItem(**row) for row in rows],
    )


@router.get(
    "/lemma/blacklist",
    response_model=LemmaBlacklistListResponse,
    summary="Просмотреть чёрный список лемм словаря",
)
def get_lemma_blacklist(
    lang: LemmaLang = Query(..., description="Словарь: ru, ru_un, ru_merged, usa, usa_un, usa_merged, frg"),
) -> LemmaBlacklistListResponse:
    return LemmaBlacklistListResponse(lang=lang, lemmas=lemma_scorer.list_blacklist(lang))


@router.post(
    "/lemma/blacklist",
    response_model=LemmaBlacklistActionResponse,
    summary="Добавить/удалить леммы в чёрном списке (action=add|remove) — исключаются из LLM-генерации и поиска трендов",
)
def lemma_blacklist_action(
    body: LemmaBlacklistActionRequest,
    lang: LemmaLang = Query(..., description="Словарь для записи: ru, ru_un, usa, usa_un, frg (merged — read-only)"),
) -> LemmaBlacklistActionResponse:
    """
    Единая ручка вместо раздельных /blacklist/add и /blacklist/remove — тот же
    паттерн, что и POST /sources/{id}/action (SourceActionRequest.action).
    """
    try:
        if body.action == "add":
            added, already_present = lemma_scorer.add_to_blacklist(lang, body.lemmas)
            return LemmaBlacklistActionResponse(
                lang=lang, action=body.action, added=added, already_present=already_present,
            )
        removed = lemma_scorer.remove_from_blacklist(lang, body.lemmas)
        return LemmaBlacklistActionResponse(lang=lang, action=body.action, removed=removed)
    except lemma_scorer.MergedLangNotWritableError as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc


@router.get(
    "/lemma/trend-candidates",
    response_model=LemmaTrendCandidatesResponse,
    summary="Эмпирические леммы: список частых в трендах за неделю(и) 3/4 (без LLM, только частоты)",
)
async def lemma_trend_candidates_endpoint(
    lang: LemmaLang = _LANG_QUERY,
    source_ids: list[int] = Query(default=[], description="Опционально: фильтр по источникам (union внутри списка)"),
    category_names: list[str] = Query(
        default=[], description="Опционально: фильтр по категориям источников (union внутри списка)"
    ),
    weeks: int = Query(4, ge=1, le=12, description="Сколько последних недель проверить"),
    min_weeks_match: int = Query(
        3, ge=1, description="Минимум недель из `weeks`, в которых лемма должна встретиться в топе"
    ),
    top_n_per_week: int = Query(30, ge=1, le=200, description="Сколько самых частых слов на неделю рассматривать"),
    min_posts: int = Query(3, ge=1, description="Минимум постов в трендовом кластере недели"),
    trending_limit: int = Query(20, ge=1, le=200, description="Максимум трендовых кластеров на неделю"),
    end_date: date | None = Query(None, description="Конец периода (по умолчанию — сегодня, UTC)"),
    db: AsyncSession = Depends(get_session),
) -> LemmaTrendCandidatesResponse:
    """
    Для каждой из последних `weeks` недель берутся трендовые кластеры этой
    недели (ретроспектива, окно 7 суток) и считается частота слов по всем их
    постам; лемма-кандидат ("эмпирическая" лемма) — та, что попала в
    top_n_per_week самых частых слов минимум в min_weeks_match неделях. Леммы
    из чёрного списка (/lemma/blacklist) исключаются из подсчёта.

    Только частотный список — без весов/категории и без обращения к LLM (lazy-load:
    веса для конкретной леммы запрашиваются отдельно через
    GET /lemma/trend-candidates/{lemma}/weights).
    """
    if min_weeks_match > weeks:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="min_weeks_match не может быть больше weeks",
        )
    return await analyze_lemma_trend_candidates.execute(
        db,
        lang=lang,
        source_ids=source_ids,
        category_names=category_names,
        weeks=weeks,
        min_weeks_match=min_weeks_match,
        top_n_per_week=top_n_per_week,
        min_posts=min_posts,
        trending_limit=trending_limit,
        end_date=end_date,
    )


@router.get(
    "/lemma/trend-candidates/{lemma}/weights",
    response_model=NewLemmaItem,
    summary="Веса ЦКМ и категория для одной леммы (lazy-load, обычно — из /lemma/trend-candidates)",
)
async def lemma_trend_candidate_weights(
    lemma: str,
    lang: LemmaLang = _LANG_QUERY,
    provider: str | None = Query(None, description="Провайдер LLM. По умолчанию — активный."),
    model: str | None = Query(None, description="Модель LLM. По умолчанию — активная."),
) -> NewLemmaItem:
    """
    Один вызов LLM — веса по 10 направлениям ЦКМ и категория для конкретной
    леммы (обычно взятой из ответа /lemma/trend-candidates, но подойдёт любое
    слово/словосочетание). Так вместо N последовательных LLM-вызовов на весь
    список сразу считаются только те леммы, что реально интересны. Результат
    можно передать в /lemma/append как есть.
    """
    return await analyze_lemma_trend_weight.execute(lemma, lang, provider=provider, model=model)


@router.post(
    "/llm/ask",
    response_model=LLMChatResponse,
    summary="Отправить произвольный текст в LLM и получить ответ",
)
async def llm_ask(body: LLMChatRequest) -> LLMChatResponse:
    text = await ask_llm(
        body.text,
        provider=body.provider,
        model=body.model,
    )
    return LLMChatResponse(text=text)


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
