"""Pydantic schemas for /api/v1/telegram."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ── Sessions ──────────────────────────────────────────────────────────────────

class TelegramSessionAddRequest(BaseModel):
    api_id: int = Field(..., description="Telegram API ID (my.telegram.org)")
    api_hash: str = Field(..., min_length=8, description="Telegram API Hash")
    session_string: str = Field(..., min_length=8, description="Telethon StringSession")
    phone: str | None = Field(None, description="Номер телефона (справочно)")
    note: str | None = Field(None, description="Произвольная метка (например, 'личный аккаунт')")


class TelegramSessionUpdateRequest(BaseModel):
    is_active: bool | None = None
    note: str | None = None
    phone: str | None = None


class TelegramSessionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    phone: str | None
    api_id: int
    # api_hash и session_string не возвращаем для безопасности
    is_active: bool
    note: str | None
    created_at: datetime
    updated_at: datetime


class TelegramSessionListResponse(BaseModel):
    items: list[TelegramSessionRead]
    total: int


class TelegramSessionCheckResponse(BaseModel):
    valid: bool
    user_id: int | None = None
    username: str | None = None
    phone: str | None = None
    first_name: str | None = None
    reason: str | None = None


# ── Resolve ───────────────────────────────────────────────────────────────────

class TelegramResolveRequest(BaseModel):
    url: str = Field(..., description="t.me/channel, @channel или просто username")


class TelegramResolvedChannel(BaseModel):
    username: str
    canonical_url: str
    id: int | None = None
    title: str | None = None
    participants_count: int | None = None
    description: str | None = None


# ── Fetch ─────────────────────────────────────────────────────────────────────

class TelegramFetchRequest(BaseModel):
    limit: int = Field(default=50, ge=1, le=500)
    force_full: bool = Field(
        default=False,
        description="Игнорировать курсор last_tg_message_id, собрать с нуля",
    )


class TelegramFetchResult(BaseModel):
    source_id: int
    username: str
    fetched_count: int
    saved_count: int
    duplicate_count: int
    last_message_id: int | None = None


class TelegramFetchPreviewResponse(BaseModel):
    username: str
    fetched_count: int
    posts: list[dict[str, Any]]
