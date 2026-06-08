from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class LemmaTextRequest(BaseModel):
    text: str = Field(..., min_length=1, description="Текст для анализа")


class LemmaSourcesRequest(BaseModel):
    source_ids: list[int] = Field(..., min_length=1, description="Список ID источников")


class LemmaAnalysisResult(BaseModel):
    """Результат анализа текста по словарному методу (lemma_coefficients_RUS.csv)."""

    schwartz_values: dict[str, float] = Field(
        ...,
        description=(
            "10 измерений ценностной картины мира (нормировано 0.0–1.0, max→1.0). "
            "Ключи совпадают с колонками CSV: Безопасность, Амбиозность и т.д."
        ),
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
