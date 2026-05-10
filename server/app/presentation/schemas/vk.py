"""Pydantic schemas for /api/v1/vk/* endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── Resolve ────────────────────────────────────────────────────────────────


class VkResolveRequest(BaseModel):
    url: str = Field(..., description="VK URL or screen_name (e.g. 'durov' or 'https://vk.com/durov')")


class VkResolvedSource(BaseModel):
    screen_name: str
    owner_id: int
    source_type: str  # vk_group | vk_public
    name: str | None = None
    members_count: int | None = None
    description: str | None = None
    site: str | None = None
    verified: bool | None = None
    photo_url: str | None = None


# ── Validate ───────────────────────────────────────────────────────────────


class VkValidateRequest(BaseModel):
    owner_id: int


class VkValidateResponse(BaseModel):
    accessible: bool
    owner_id: int
    reason: str | None = None


# ── Metadata ───────────────────────────────────────────────────────────────


class VkGroupMetadata(BaseModel):
    owner_id: int
    name: str | None = None
    screen_name: str | None = None
    description: str | None = None
    members_count: int | None = None
    verified: bool | None = None
    site: str | None = None
    activity: str | None = None
    photo_url: str | None = None
    cover_url: str | None = None
    fetched_at: datetime | None = None


class VkMetadataRefreshResponse(BaseModel):
    source_id: int
    refreshed: bool
    metadata: VkGroupMetadata | None = None
    error: str | None = None


# ── Fetch ──────────────────────────────────────────────────────────────────


class VkFetchRequest(BaseModel):
    limit: int = Field(200, ge=1, le=5000, description="Max posts to collect")
    skip_ads: bool = False
    skip_pinned: bool = False


class VkHistoricalFetchRequest(BaseModel):
    date_from: datetime
    date_to: datetime | None = None
    max_posts: int = Field(5000, ge=1, le=50000)
    skip_ads: bool = False


class VkFetchResult(BaseModel):
    source_id: int
    owner_id: int
    fetched_count: int
    saved_count: int
    duplicate_count: int
    stopped_by: str
    latest_post_id: str | None = None


class VkFetchPreviewRequest(BaseModel):
    limit: int = Field(20, ge=1, le=100)
    skip_ads: bool = False


class VkFetchPreviewResponse(BaseModel):
    owner_id: int
    posts: list[dict[str, Any]]
    fetched_count: int


# ── Collection State ───────────────────────────────────────────────────────


class VkCollectionState(BaseModel):
    source_id: int
    owner_id: int | None = None
    last_vk_post_id: str | None = None
    total_collected: int | None = None
    last_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    error_count: int | None = None
    last_error_at: datetime | None = None


class VkStateResetResponse(BaseModel):
    source_id: int
    reset: bool


# ── Token management ───────────────────────────────────────────────────────


class VkTokenAddRequest(BaseModel):
    access_token: str = Field(..., min_length=10)


class VkTokenRead(BaseModel):
    id: int
    usage: int
    is_active: bool
    last_used_at: datetime | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class VkTokenCheckRequest(BaseModel):
    access_token: str


class VkTokenCheckResponse(BaseModel):
    valid: bool
    user: dict[str, Any] | None = None
    reason: str | None = None
    code: int | None = None


class VkTokenRotateResponse(BaseModel):
    deactivated_id: int
    new_id: int
    new_token_valid: bool


class VkTokenListResponse(BaseModel):
    items: list[VkTokenRead]
    total: int
