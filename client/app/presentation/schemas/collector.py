from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class CollectRequest(BaseModel):
    count: int = Field(default=10, ge=1, le=100)
    use_mock: bool = False


class CollectResponse(BaseModel):
    collected: int
    posts: list[dict[str, Any]] = Field(default_factory=list)


class PublicCollectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: str | None = Field(None, max_length=512)
    url: str = Field(..., min_length=8, description="Ссылка на паблик https://vk.com/…")
    limit: int = Field(default=20, ge=1, le=100)
    use_mock: bool = False


class PublicCollectResponse(BaseModel):
    """Payload для сервера после wall.get (без записи в БД на стороне клиента)."""

    url: str
    vk_owner_id: int
    collected: int
    posts: list[dict[str, Any]]
    mock: bool = False


class RssCollectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., min_length=8, description="URL RSS или Atom ленты (http/https)")
    limit: int = Field(default=20, ge=1, le=200)
    use_mock: bool = False


class RssCollectResponse(BaseModel):
    """Записи ленты для оркестрации (без записи в БД на стороне клиента)."""

    url: str
    feed_title: str | None = None
    collected: int
    items: list[dict[str, Any]]
    mock: bool = False


class TelegramCollectRequest(BaseModel):
    model_config = ConfigDict(extra="ignore")

    url: str = Field(..., min_length=3, description="t.me/channel или @channel")
    limit: int = Field(default=20, ge=1, le=200)


class TelegramCollectResponse(BaseModel):
    """Посты Telegram-канала для оркестрации."""

    url: str
    channel_title: str | None = None
    collected: int
    posts: list[dict[str, Any]]
