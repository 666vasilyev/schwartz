from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.application.services.content.lemma_llm_extractor import TARGET_COUNT as _DEFAULT_LEMMA_COUNT
from app.application.services.content.lemma_scorer import LemmaLang
from app.use_case.analyze._time_utils import TimeGranularity

__all__ = ["TimeGranularity"]  # re-export so routes can import from one place


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


class LemmaExtractRequest(BaseModel):
    """Запрос на извлечение новых лемм для словаря через LLM (текст не сохраняется, только анализируется)."""

    text: str = Field(..., min_length=1, description="Текст (например, выступление) для анализа")
    count: int = Field(
        _DEFAULT_LEMMA_COUNT,
        ge=1,
        le=20,
        description=(
            "Сколько новых лемм подобрать (LLM вызывается по одной лемме за раз, "
            "так что большие значения заметно увеличивают время ответа)"
        ),
    )
    provider: str | None = Field(None, description="Провайдер LLM. По умолчанию — активный.")
    model: str | None = Field(None, description="Модель LLM. По умолчанию — активная.")


class NewLemmaItem(BaseModel):
    """Одна кандидатная лемма с весами по 10 измерениям ЦКМ (порядок соответствует колонкам CSV)."""

    lemma: str = Field(..., min_length=1, description="Лемма или устойчивое словосочетание")
    weights: dict[str, float] = Field(
        ...,
        description="Вес 0.0–1.0 по каждому из 10 измерений ЦКМ (ключи — названия колонок CSV)",
    )
    category: str = Field("", description="Категория(и) через ' / ', как в исходных CSV-словарях")


class LemmaExtractResponse(BaseModel):
    """Кандидаты LLM на добавление в словарь — ничего не сохраняется, только предпросмотр."""

    lang: LemmaLang
    already_matched: list[str] = Field(
        default_factory=list,
        description="Леммы словаря, уже встретившиеся в тексте (LLM просили их не повторять)",
    )
    lemmas: list[NewLemmaItem] = Field(
        default_factory=list,
        description=(
            "До `count` новых лемм (см. запрос), не повторяющихся со словарём и друг с другом. "
            "Ключ совпадает с полем `lemmas` в /lemma/append — весь этот ответ можно "
            "передать в append как есть (лишние поля lang/already_matched будут проигнорированы)."
        ),
    )


class LemmaListResponse(BaseModel):
    """Текущее содержимое CSV-словаря — просмотр перед/после ручного редактирования."""

    lang: LemmaLang
    total: int = Field(description="Всего лемм в словаре после фильтра search (если задан)")
    offset: int
    limit: int
    lemmas: list[NewLemmaItem] = Field(default_factory=list, description="Страница строк, отсортировано по лемме")


class LemmaAppendRequest(BaseModel):
    """Запрос на дозапись лемм (вручную или результат /lemma/extract) в CSV-словарь."""

    lemmas: list[NewLemmaItem] = Field(..., min_length=1, max_length=50)


class LemmaAppendResponse(BaseModel):
    """Результат добавления/обновления лемм в CSV-словаре (upsert)."""

    lang: LemmaLang
    added: int = Field(description="Сколько лемм было новыми и дописано в конец CSV")
    updated: int = Field(0, description="Сколько лемм уже было в словаре — их старые строки заменены новыми значениями")
    skipped_duplicates: list[str] = Field(
        default_factory=list,
        description="Леммы, пропущенные как повтор внутри одного запроса (одна и та же лемма дважды)",
    )


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
    """ЦКМ категории по словарному методу за один период (день / неделя / месяц)."""

    period_start: date = Field(description="Начало периода (день, понедельник недели или первый день месяца)")
    posts_total: int = Field(description="Всего постов категории за период")
    posts_analyzed: int = Field(description="Постов с непустым текстом, прошедших анализ")
    posts_skipped_empty: int = 0
    aggregate_schwartz: dict[str, float] = Field(
        ...,
        description="Среднее по 10 измерениям ЦКМ за период (нормировано: сумма = 1.0)",
    )
    aggregate_categories: dict[str, float] = Field(
        default_factory=dict,
        description="Нормированная частота категорий слов за период (сумма = 1.0)",
    )


class CategoryLemmaByDayResponse(BaseModel):
    """ЦКМ категории по словарному методу, в разбивке по периодам (день / неделя / месяц)."""

    category_name: str
    granularity: str = Field(description="Гранулярность: day, week, month")
    periods: list[CategoryLemmaDayItem] = Field(
        default_factory=list,
        description="По одной записи на каждый период; отсортировано по убыванию period_start",
    )


class CategoriesSchwartzTimeseriesResponse(BaseModel):
    """
    Временны́е ряды ЦКМ по нескольким категориям.

    Структура data: data[параметр_шварца][категория] = [значение_за_период_0, значение_за_период_1, ...]
    Индексы значений соответствуют индексам в списке periods.
    """

    granularity: str = Field(description="Гранулярность: day, week, month")
    periods: list[date] = Field(description="Список начал периодов по возрастанию")
    posts_count: dict[str, list[int]] = Field(
        description="posts_count[категория] = [кол-во постов за период_0, за период_1, ...]",
    )
    data: dict[str, dict[str, list[float]]] = Field(
        description="data[параметр_шварца][категория] = [значение за каждый период]",
    )


class LLMChatRequest(BaseModel):
    """Произвольный запрос к LLM-модели."""

    text: str = Field(..., min_length=1, description="Текст пользователя")
    provider: str | None = Field(None, description="Провайдер (напр. ollama). По умолчанию — активный.")
    model: str | None = Field(None, description="Модель (напр. gemma4:31b). По умолчанию — активная.")


class LLMChatResponse(BaseModel):
    """Ответ LLM-модели на произвольный запрос."""

    text: str = Field(description="Текст ответа модели")


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
