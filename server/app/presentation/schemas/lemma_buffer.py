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


class LemmaBufferActionRequest(BaseModel):
    """
    Единый запрос на изменение буфера — action выбирает операцию (тот же
    паттерн, что и POST /lemma/blacklist):
      - add — добавить/повторно отметить фрагменты из `items` (повтор той же
        леммы увеличивает счётчик, а не создаёт дубль);
      - remove — убрать леммы из `lemmas` (сверяются после нормализации);
      - clear — очистить весь буфер текущего пользователя (items/lemmas игнорируются).
    """

    action: Literal["add", "remove", "clear"]
    items: list[LemmaBufferAddItem] = Field(default_factory=list, max_length=50)
    lemmas: list[str] = Field(default_factory=list, max_length=200)


class LemmaBufferActionResponse(BaseModel):
    action: Literal["add", "remove", "clear"]
    added: int = Field(0, description="Сколько новых лемм добавлено (только action=add)")
    updated: int = Field(
        0, description="Сколько уже существующих лемм повторно отмечено, times_selected++ (только action=add)"
    )
    removed: int = Field(0, description="Сколько записей удалено (action=remove или clear)")


class LemmaBufferItem(BaseModel):
    lemma: str
    raw_text: str = Field(description="Последняя выделенная форма (может отличаться от lemma регистром/формой)")
    times_selected: int = Field(description="Сколько раз пользователь выделял эту лемму")
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
        description="Отсортировано: сначала по times_selected (убыв.), затем по last_seen_at (убыв.)",
    )
