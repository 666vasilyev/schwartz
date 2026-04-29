from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.infrastructure.db.orm.models import SourceStatus


class SourceCreateRequest(BaseModel):
    """Регистрация источника: VK (паблик) или RSS/Atom (URL ленты)."""

    url: str = Field(..., min_length=4, description="Ссылка на паблик VK или на RSS/Atom")
    name: str | None = Field(None, max_length=512)
    source: str = Field(default="vk", description="vk или rss")

    @field_validator("source")
    @classmethod
    def normalize_source(cls, v: str) -> str:
        s = (v or "vk").strip().lower()
        if s not in ("vk", "rss"):
            raise ValueError("Поле source должно быть vk или rss")
        return s


class SourceUpdateRequest(BaseModel):
    """Частичное обновление источника: только переданные поля."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=512)
    url: str | None = Field(None, min_length=4)
    status: SourceStatus | None = None
    vk_owner_id: int | None = None
    error_message: str | None = None
    last_run_at: datetime | None = None


class SourceRead(BaseModel):
    """Строка списка источников (как в Figma: id, название, ссылка, статус, дата)."""

    id: int
    name: str | None = None
    url: str
    source: str = "vk"
    status: SourceStatus
    last_run_at: datetime | None = None
    error_message: str | None = None
    vk_owner_id: int | None = None
    extra: dict | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class SourceListResponse(BaseModel):
    items: list[SourceRead]
    total: int
    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)
