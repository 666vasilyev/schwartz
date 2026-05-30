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

    model_config = {"from_attributes": True}


class PostRead(BaseModel):
    """Полное представление поста для GET /posts."""

    id: int
    source_id: int | None = None
    source_type: str | None = None
    external_id: str | None = None
    vk_post_id: str | None = None
    owner_id: int | None = None
    text: str | None = None
    published_at: datetime | None = None
    is_ad: bool = False
    reactions: dict[str, Any] | None = None
    attachments: list[Any] | None = None
    payload: dict[str, Any] | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class PostListResponse(BaseModel):
    items: list[PostRead]
    total: int
    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
