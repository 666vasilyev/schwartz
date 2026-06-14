from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.application.services.content.lemma_scorer import LemmaLang


class LLMOverrideRequest(BaseModel):
    """Опциональное тело запроса для переопределения LLM-провайдера и модели."""
    provider: str | None = Field(
        default=None,
        description="Провайдер LLM: openai, deepseek, gigachat, yandexgpt. По умолчанию — активный.",
    )
    model: str | None = Field(
        default=None,
        description="Название модели. По умолчанию — активная модель провайдера.",
    )


class LemmaTextRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст для анализа")


class LemmaSourcesRequest(BaseModel):
    source_ids: list[int] = Field(..., min_length=1, description="Список ID источников")


class CategoryLangItem(BaseModel):
    category_name: str = Field(..., description="Имя категории")
    lang: LemmaLang = Field(LemmaLang.ru, description="Язык словаря для этой категории")


class LemmaCategoriesRequest(BaseModel):
    categories: list[CategoryLangItem] = Field(..., min_length=1, description="Список категорий с языком")


class LemmaBaselineResponse(BaseModel):
    label: str
    schwartz_values: dict[str, float]


class LemmaAnalysisResult(BaseModel):
    """Результат анализа текста по словарному методу."""

    schwartz_values: dict[str, float] = Field(
        ...,
        description="10 измерений ЦКМ (нормировано: сумма = 1.0)",
    )
    category_frequencies: dict[str, float] = Field(
        default_factory=dict,
        description="Нормированная частота категорий слов из CSV (сумма = 1.0), отсортировано по убыванию",
    )
    matched_count: int = Field(..., description="Число совпавших лемм в тексте")
    matched_lemmas: list[str] = Field(
        default_factory=list,
        description="Список найденных лемм (для отладки)",
    )


class SourceLemmaAnalysisResponse(BaseModel):
    """Агрегат ЦКМ по источнику или категории через словарный метод."""

    source_id: int | None = None
    category_name: str | None = None
    posts_total: int = Field(description="Всего постов в выборке")
    posts_analyzed: int = Field(description="Постов с непустым текстом, прошедших анализ")
    posts_skipped_empty: int = 0
    aggregate_schwartz: dict[str, float] = Field(
        ...,
        description="Среднее по 10 измерениям ЦКМ (нормировано: сумма = 1.0)",
    )
    aggregate_categories: dict[str, float] = Field(
        default_factory=dict,
        description="Нормированная частота категорий слов по всем постам (сумма = 1.0)",
    )


class CategoryLemmaDayItem(BaseModel):
    """ЦКМ категории по словарному методу за один день (по дате публикации постов)."""

    date: date
    posts_total: int = Field(description="Всего постов категории за этот день")
    posts_analyzed: int = Field(description="Постов с непустым текстом, прошедших анализ")
    posts_skipped_empty: int = 0
    aggregate_schwartz: dict[str, float] = Field(
        ...,
        description="Среднее по 10 измерениям ЦКМ за день (нормировано: сумма = 1.0)",
    )
    aggregate_categories: dict[str, float] = Field(
        default_factory=dict,
        description="Нормированная частота категорий слов за день (сумма = 1.0)",
    )


class CategoryLemmaByDayResponse(BaseModel):
    """ЦКМ категории по словарному методу, в разбивке по дням публикации (вместо одного агрегата за весь период)."""

    category_name: str
    days: list[CategoryLemmaDayItem] = Field(
        default_factory=list,
        description="По одной записи на каждый день, где есть посты; отсортировано по убыванию даты",
    )


class ContentAnalysisResult(BaseModel):
    """Результат анализа поста: деструктивность по тексту (LLM) + 10 измерений Шварца (LLM, только в рантайме/ответе)."""
    destruct_score: float = Field(..., ge=0.0)
    schwartz_values: dict[str, float] | None = None
    text_score: float = Field(0.0, ge=0.0)
    details: dict = Field(default_factory=dict)


class SourceAnalyzeResponse(BaseModel):
    """Краткий итог анализа источника: счётчики и средние Шварца (в БД сохраняются те же средние, без округления в расчёте)."""

    source_id: int
    vk_owner_id: int | None = None
    posts_total_in_db: int = Field(
        description="Всего постов в БД для этого источника (по owner_id или source_id)"
    )
    posts_in_run: int = Field(
        description="Сколько постов взято в этот прогон (после limit)",
    )
    posts_analyzed: int = Field(description="Сколько постов реально ушли в LLM")
    posts_skipped_empty_text: int = 0
    aggregate_schwartz: dict[str, float] = Field(
        ...,
        description="Среднее по Шварцу; в JSON значения округлены до 4 знаков",
    )


class SourceStoredSchwartzResponse(BaseModel):
    """Сохранённый в БД агрегат Шварца для источника (без вызова LLM)."""

    source_id: int
    vk_owner_id: int | None = None
    aggregate_schwartz: dict[str, float] = Field(
        ...,
        description="Значения из source_schwartz_analysis, округление до 4 знаков",
    )
    analyzed_at: datetime


class VkPostItem(BaseModel):
    """Метаданные одного поста (стена, collect)."""
    db_post_id: int | None = Field(None, description="DB primary key after saving to DB")
    vk_post_id: str
    owner_id: int | None = None
    text: str | None = None
    published_at: str | None = None
    is_ad: bool = False
    comments: list[dict[str, Any]] = Field(default_factory=list)
    reactions: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class VkPostList(BaseModel):
    posts: list[VkPostItem]
    total: int
    saved_to_db: int = Field(0, description="Сколько постов сохранено в БД в этом запросе")
