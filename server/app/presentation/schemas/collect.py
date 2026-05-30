from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.presentation.schemas.analysis import VkPostItem


class CollectVkPublicPostItem(BaseModel):
    """Пост со стены паблика — с клиента после wall.get (+ комментарии и обогащение)."""

    model_config = ConfigDict(extra="ignore")

    vk_post_id: str
    owner_id: int
    text: str | None = None
    published_at: str | None = None
    is_ad: bool = False
    comments: list[dict[str, Any]] = Field(default_factory=list)
    reactions: dict[str, Any] = Field(default_factory=dict)
    attachments: list[dict[str, Any]] = Field(default_factory=list)


class CollectTelegramPostItem(BaseModel):
    """Пост Telegram-канала — с клиента после /collect/telegram."""

    model_config = ConfigDict(extra="ignore")

    external_id: str
    text: str | None = None
    published_at: str | None = None
    views: int = 0
    reactions: dict[str, Any] = Field(default_factory=dict)
    comments: int = 0
    media_urls: list[str] = Field(default_factory=list)
    is_forwarded: bool = False


class CollectRssPublicItem(BaseModel):
    """Запись ленты — с клиента после /collect/rss."""

    rss_id: str
    title: str | None = None
    link: str | None = None
    published: str | None = None
    text: str | None = None


class CollectVkPublicResponse(BaseModel):
    source_id: int
    name: str | None = None
    source: str = Field(default="vk")
    status: str
    url: str
    vk_owner_id: int | None = None
    posts: list[VkPostItem]
    total: int
    saved_to_db: int
