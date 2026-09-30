from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class PostInput(BaseModel):
    """Пост на анализ: только текст и идентификаторы VK."""

    vk_post_id: str | None = Field(None, description="ID поста в VK")
    owner_id: int | None = Field(None, description="owner_id владельца стены/поста")
    text: str | None = Field(None, description="Текст поста")


class PostResponse(BaseModel):
    id: int
    vk_post_id: str | None
    owner_id: int | None
    text: str | None
    published_at: datetime | None = None
    is_ad: bool = False
    reactions: dict[str, Any] | None = None
    attachments: list[Any] | None = None
    payload: dict[str, Any] | None = None
    image_url: str | None = Field(
        None, description="Картинка поста, либо (если в посте своей нет) картинка источника"
    )

    model_config = {"from_attributes": True}


class PostRead(BaseModel):
    """Полное представление поста для GET /posts."""

    id: int
    source_id: int | None = None
    source_type: str | None = None
    url: str | None = None
    external_id: str | None = None
    text: str | None = None
    published_at: datetime | None = None
    is_ad: bool = False
    reactions: dict[str, Any] | None = None
    attachments: list[Any] | None = None
    payload: dict[str, Any] | None = None
    image_url: str | None = Field(
        None, description="Картинка поста, либо (если в посте своей нет) картинка источника"
    )
    created_at: datetime

    model_config = {"from_attributes": True}


class PostSummaryRequest(BaseModel):
    """Саммари по постам, выбранным пользователем на фронте (POST /api/v1/posts/summary)."""

    post_ids: list[int] = Field(..., min_length=1, max_length=20, description="ID постов (до 20 за раз)")


class PostSummaryReportRequest(BaseModel):
    """
    Тело POST /api/v1/posts/summary/report.

    title/summary/topics — опциональны: если summary передан (не пустой),
    саммари берётся с экрана как есть и LLM повторно НЕ вызывается — так
    отчёт гарантированно совпадает с тем, что человек уже видел после
    POST /summary (в т.ч. если он сам отредактировал текст). Если summary не
    передан — саммари строится заново тем же LLM-вызовом, что и в /summary
    (обратная совместимость со старым поведением).
    """

    post_ids: list[int] = Field(..., min_length=1, max_length=20, description="ID постов (до 20 за раз)")
    title: str | None = Field(
        None, description="Заголовок с экрана (после POST /summary) — если передан вместе с summary, LLM не вызывается"
    )
    summary: str | None = Field(None, description="Текст саммари с экрана — если пуст, саммари строится заново через LLM")
    topics: list[str] = Field(default_factory=list, description="Темы с экрана (используются только вместе с summary)")


class PostSummaryResponse(BaseModel):
    title: str | None = Field(None, description="Короткий заголовок сюжета")
    summary: str | None = Field(None, description="Саммари в 1-3 предложениях")
    topics: list[str] = Field(default_factory=list, description="1-4 коротких ярлыка темы")
    posts_used: int = Field(description="Сколько постов реально попало в промпт (с непустым текстом)")
    missing_post_ids: list[int] = Field(
        default_factory=list, description="ID из запроса, которых не нашлось в БД"
    )
    empty_text_post_ids: list[int] = Field(
        default_factory=list, description="Найдены, но без текста — не учтены в саммари"
    )


class PostListResponse(BaseModel):
    items: list[PostRead]
    total: int
    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
