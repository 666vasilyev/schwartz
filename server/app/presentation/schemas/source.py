from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.infrastructure.db.orm.models import SourceStatus, SourceType


# ── Request schemas ────────────────────────────────────────────────────────


class SourceCreateRequest(BaseModel):
    url: str = Field(..., min_length=4, description="Ссылка на паблик VK или на RSS/Atom")
    name: str | None = Field(None, max_length=512)
    source_type: SourceType | None = Field(None, description="Тип источника")
    # Backward-compat field; if set, used to derive source_type/platform
    source: str = Field(default="vk", description="vk или rss (legacy)")
    description: str | None = None
    priority: int = Field(default=0, ge=0)
    fetch_interval_minutes: int = Field(default=60, ge=1)
    auth_required: bool = False
    collection_policy: dict | None = None
    content_policy: dict | None = None
    media_policy: dict | None = None
    language_hint: str | None = Field(None, max_length=16)
    region_hint: str | None = Field(None, max_length=64)
    topic_hint: str | None = Field(None, max_length=255)
    owner_id: int | None = None
    category_id: int | None = Field(None, description="ID категории из /api/v1/source-categories")

    @field_validator("source")
    @classmethod
    def normalize_source(cls, v: str) -> str:
        s = (v or "vk").strip().lower()
        if s not in ("vk", "rss"):
            raise ValueError("Поле source должно быть vk или rss")
        return s


class SourceUpdateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, max_length=512)
    url: str | None = Field(None, min_length=4)
    description: str | None = None
    status: SourceStatus | None = None
    source_type: SourceType | None = None
    platform: str | None = None
    username: str | None = None
    external_id: str | None = None
    priority: int | None = Field(None, ge=0)
    fetch_interval_minutes: int | None = Field(None, ge=1)
    auth_required: bool | None = None
    collection_policy: dict | None = None
    content_policy: dict | None = None
    media_policy: dict | None = None
    language_hint: str | None = Field(None, max_length=16)
    region_hint: str | None = Field(None, max_length=64)
    topic_hint: str | None = Field(None, max_length=255)
    owner_id: int | None = None
    category_id: int | None = None
    # Legacy fields
    vk_owner_id: int | None = None
    error_message: str | None = None
    last_run_at: datetime | None = None


# ── Bulk schemas ───────────────────────────────────────────────────────────


class BulkCreateRequest(BaseModel):
    sources: list[SourceCreateRequest] = Field(..., min_length=1, max_length=100)


class BulkUpdateItem(BaseModel):
    id: int = Field(..., ge=1)
    data: SourceUpdateRequest


class BulkUpdateRequest(BaseModel):
    sources: list[BulkUpdateItem] = Field(..., min_length=1, max_length=100)


# ── Response schemas ───────────────────────────────────────────────────────


class SourceRead(BaseModel):
    id: int
    name: str | None = None
    url: str
    source: str = "vk"
    source_type: str | None = None
    platform: str | None = None
    username: str | None = None
    external_id: str | None = None
    description: str | None = None
    status: SourceStatus
    priority: int = 0
    fetch_interval_minutes: int = 60
    last_fetch_at: datetime | None = None
    next_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    error_count: int = 0
    auth_required: bool = False
    collection_policy: dict | None = None
    content_policy: dict | None = None
    media_policy: dict | None = None
    language_hint: str | None = None
    region_hint: str | None = None
    topic_hint: str | None = None
    owner_id: int | None = None
    category_id: int | None = None
    source_metadata: dict | None = None
    # Legacy
    last_run_at: datetime | None = None
    error_message: str | None = None
    vk_owner_id: int | None = None
    extra: dict | None = None
    deleted_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True, populate_by_name=True)


class SourceListResponse(BaseModel):
    items: list[SourceRead]
    total: int
    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=500)


class BulkCreateResponse(BaseModel):
    created: list[SourceRead]
    # errors: list[dict[str, Any]]

class BulkCreateResponseErrors(BaseModel):
    errors: list[dict[str, Any]]


class BulkUpdateResponse(BaseModel):
    updated: list[SourceRead]
    errors: list[dict[str, Any]]


# ── Stats / Health ─────────────────────────────────────────────────────────


class SourceStats(BaseModel):
    source_id: int
    total_posts: int
    total_comments: int
    posts_last_24h: int
    posts_last_7d: int
    last_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    error_count: int


class SourceHealth(BaseModel):
    source_id: int
    status: SourceStatus
    is_healthy: bool
    error_count: int
    last_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    last_error_at: datetime | None = None
    next_fetch_at: datetime | None = None
    error_message: str | None = None


# ── Validate / Refresh-metadata ────────────────────────────────────────────


class SourceValidateResponse(BaseModel):
    source_id: int
    reachable: bool
    detail: str | None = None
    resolved_metadata: dict | None = None


class SourceRefreshMetadataResponse(BaseModel):
    source_id: int
    updated: bool
    source_metadata: dict | None = None


# ── Audit log ──────────────────────────────────────────────────────────────


class AuditLogRead(BaseModel):
    id: int
    source_id: int
    action: str
    actor_id: int | None = None
    previous: dict | None = None
    changes: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AuditLogListResponse(BaseModel):
    items: list[AuditLogRead]
    total: int
    skip: int
    limit: int


# ── Jobs (stub) ─────────────────────────────────────────────────────────────


class JobRead(BaseModel):
    id: str
    source_id: int
    status: str
    started_at: datetime | None = None
    finished_at: datetime | None = None
    detail: str | None = None


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int


# ── Action ──────────────────────────────────────────────────────────────────

SourceAction = Literal[
    "enable",
    "disable",
    "pause",
    "reset_error",
    "fetch",
    "fetch_history",
    "fetch_incremental",
]


class SourceActionRequest(BaseModel):
    """Единый запрос на действие над источником."""

    action: SourceAction

    # ── параметры для fetch-действий (игнорируются при status-переходах) ──
    limit: int | None = Field(None, ge=1, le=50_000, description="Лимит постов (fetch/*)")
    priority: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    correlation_id: str | None = Field(None, max_length=128)
    params: dict[str, Any] | None = None

    # ── только для fetch_history ──────────────────────────────────────────
    date_from: datetime | None = None
    date_to: datetime | None = None


class SourceActionResponse(BaseModel):
    """Ответ на action-запрос.
    При status-переходах заполняется source, при fetch — job.
    """

    action: str
    source: SourceRead | None = None
    # JobRead из collection_job импортируется в use_case; здесь храним как dict
    # чтобы не создавать циклический импорт между schema-модулями.
    job: dict[str, Any] | None = None
