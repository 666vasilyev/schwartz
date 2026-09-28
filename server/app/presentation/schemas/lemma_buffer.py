from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from app.application.services.content.lemma_scorer import LemmaLang


class LemmaBufferAddItem(BaseModel):
    """Один фрагмент, выделенный пользователем на фронте (слово/словосочетание)."""

    text: str = Field(..., min_length=1, max_length=200, description="Выделенный текст как есть")
    source_post_id: int | None = Field(None, description="ID поста, где было выделение (опционально)")
    source_cluster_id: int | None = Field(
        None, description="ID сюжетного кластера, где было выделение (опционально)"
    )


class LemmaBufferWeightsItem(BaseModel):
    """
    Веса ЦКМ для одной леммы буфера — сохранить результат LLM-генерации
    (GET /lemma/trend-candidates/{lemma}/weights) или введённые вручную на
    фронте значения. Формат идентичен NewLemmaItem из /lemma/append.
    """

    lemma: str = Field(..., min_length=1, description="Должна уже быть в буфере (см. action=add)")
    weights: dict[str, float] = Field(..., description="Вес 0.0–1.0 по каждому из 10 измерений ЦКМ")
    category: str = Field("", description="Категория(и) через ' / ', как в CSV-словарях")


class LemmaBufferActionRequest(BaseModel):
    """
    Единый запрос на изменение буфера — action выбирает операцию (тот же
    паттерн, что и POST /lemma/blacklist):
      - add — добавить фрагменты из `items`. Повторное выделение уже
        сохранённой леммы не создаёт дубль и не меняет её место в буфере;
      - set_weights — сохранить веса/категорию для лемм из `weights_items`
        (лемма уже должна быть в буфере — см. add). Леммы не из буфера
        попадают в `not_found` ответа и пропускаются;
      - remove — убрать леммы из `lemmas` (сверяются после нормализации);
      - clear — очистить весь буфер текущего пользователя (остальные поля игнорируются);
      - generate_weights — пакетно сгенерировать веса/категорию через LLM для
        лемм буфера (по умолчанию только тех, у кого weights ещё не заданы —
        см. `overwrite`), сразу сохранить результат в буфер. Обязателен `lang`
        (от него зависит список категорий, которые предлагаются LLM). За один
        вызов обрабатывается не больше `limit` лемм (LLM-вызовы
        последовательные, по одному на лемму — см. assign_weights_to_lemmas);
        если лемм больше — вызывать снова, пока в ответе remaining не станет 0.
    """

    action: Literal["add", "set_weights", "remove", "clear", "generate_weights"]
    items: list[LemmaBufferAddItem] = Field(default_factory=list, max_length=50)
    weights_items: list[LemmaBufferWeightsItem] = Field(default_factory=list, max_length=50)
    lemmas: list[str] = Field(default_factory=list, max_length=200)
    lang: LemmaLang | None = Field(None, description="Обязателен при action=generate_weights")
    overwrite: bool = Field(
        False, description="action=generate_weights: пересчитать и для лемм, у которых веса уже есть"
    )
    limit: int = Field(50, ge=1, le=50, description="action=generate_weights: сколько лемм обработать за раз")
    provider: str | None = Field(None, description="action=generate_weights: провайдер LLM (по умолчанию — активный)")
    model: str | None = Field(None, description="action=generate_weights: модель LLM (по умолчанию — активная)")


class LemmaBufferActionResponse(BaseModel):
    action: Literal["add", "set_weights", "remove", "clear", "generate_weights"]
    added: int = Field(0, description="Сколько новых лемм добавлено (только action=add)")
    updated: int = Field(
        0,
        description=(
            "action=add — сколько лемм уже было в буфере (повторное выделение, без дубля); "
            "action=set_weights — сколько лемм получили сохранённые веса/категорию; "
            "action=generate_weights — сколько лемм успешно сгенерировано и сохранено"
        ),
    )
    removed: int = Field(0, description="Сколько записей удалено (action=remove или clear)")
    not_found: list[str] = Field(
        default_factory=list,
        description="action=set_weights — леммы, которых нет в буфере пользователя (пропущены)",
    )
    failed: list[str] = Field(
        default_factory=list,
        description="action=generate_weights — леммы, для которых LLM не вернула разбираемый ответ (не сохранены, weights остались NULL — можно повторить)",
    )
    generated: list[LemmaBufferWeightsItem] = Field(
        default_factory=list,
        description="action=generate_weights — сгенерированные {lemma, weights, category}, в формате /lemma/append",
    )
    remaining: int = Field(
        0,
        description="action=generate_weights — сколько лемм ещё осталось без весов после этого вызова (лимит за раз — limit)",
    )


class LemmaBufferItem(BaseModel):
    """
    Формат {lemma, weights, category} совпадает с NewLemmaItem из
    /lemma/append — когда weights/category заполнены, весь объект можно
    передать в append.lemmas как есть (остальные поля будут проигнорированы).
    """

    lemma: str
    weights: dict[str, float] | None = Field(
        None, description="Веса ЦКМ, если уже сохранены (action=set_weights) — иначе null"
    )
    category: str | None = Field(None, description="Категория, если уже сохранена — иначе null")
    raw_text: str = Field(description="Последняя выделенная форма (может отличаться от lemma регистром/формой)")
    first_seen_at: datetime
    last_seen_at: datetime
    source_post_id: int | None = None
    source_cluster_id: int | None = None
    in_dictionary: bool = Field(description="Уже есть такая лемма в словаре lang")
    in_blacklist: bool = Field(description="В чёрном списке lang — исключена бы из подсказок при генерации")


class LemmaBufferListResponse(BaseModel):
    lang: LemmaLang
    total: int
    offset: int
    limit: int
    items: list[LemmaBufferItem] = Field(
        default_factory=list,
        description="Отсортировано по first_seen_at (первая выделенная лемма — первая в списке)",
    )
