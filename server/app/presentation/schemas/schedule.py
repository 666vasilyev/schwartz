"""Pydantic schemas for /api/v1/schedule/* endpoints."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ── ScheduleRule ───────────────────────────────────────────────────────────


class ScheduleRuleCreateRequest(BaseModel):
    rule_type: str = Field(..., pattern="^(source|platform|group)$")
    source_id: int | None = None
    platform: str | None = None
    group_name: str | None = None
    base_interval_minutes: int = Field(60, ge=1, le=10080)
    min_interval_minutes: int = Field(5, ge=1, le=10080)
    max_interval_minutes: int = Field(10080, ge=1, le=525600)  # 1 year max
    error_backoff_multiplier: float = Field(1.5, ge=1.0, le=10.0)
    max_error_backoff_minutes: int = Field(480, ge=5, le=10080)
    priority_boost_enabled: bool = False
    night_mode_enabled: bool = False
    night_start_hour: int = Field(23, ge=0, le=23)
    night_end_hour: int = Field(7, ge=0, le=23)
    night_interval_minutes: int = Field(360, ge=1, le=1440)
    max_jobs_per_hour: int = Field(60, ge=1, le=3600)
    max_concurrent_jobs: int = Field(5, ge=1, le=100)
    is_enabled: bool = True
    description: str | None = None


class ScheduleRuleUpdateRequest(BaseModel):
    base_interval_minutes: int | None = Field(None, ge=1, le=10080)
    min_interval_minutes: int | None = Field(None, ge=1, le=10080)
    max_interval_minutes: int | None = Field(None, ge=1, le=525600)
    error_backoff_multiplier: float | None = Field(None, ge=1.0, le=10.0)
    max_error_backoff_minutes: int | None = Field(None, ge=5, le=10080)
    priority_boost_enabled: bool | None = None
    night_mode_enabled: bool | None = None
    night_start_hour: int | None = Field(None, ge=0, le=23)
    night_end_hour: int | None = Field(None, ge=0, le=23)
    night_interval_minutes: int | None = Field(None, ge=1, le=1440)
    max_jobs_per_hour: int | None = Field(None, ge=1, le=3600)
    max_concurrent_jobs: int | None = Field(None, ge=1, le=100)
    is_enabled: bool | None = None
    description: str | None = None


class ScheduleRuleRead(BaseModel):
    id: int
    rule_type: str
    source_id: int | None = None
    platform: str | None = None
    group_name: str | None = None
    base_interval_minutes: int
    min_interval_minutes: int
    max_interval_minutes: int
    error_backoff_multiplier: float
    max_error_backoff_minutes: int
    priority_boost_enabled: bool
    night_mode_enabled: bool
    night_start_hour: int
    night_end_hour: int
    night_interval_minutes: int
    max_jobs_per_hour: int
    max_concurrent_jobs: int
    is_enabled: bool
    description: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ScheduleRuleListResponse(BaseModel):
    items: list[ScheduleRuleRead]
    total: int


# ── Upcoming runs ──────────────────────────────────────────────────────────


class UpcomingRun(BaseModel):
    source_id: int
    source_name: str | None = None
    rule_id: int | None = None
    scheduled_at: datetime
    calculated_interval_minutes: float | None = None


class UpcomingRunsResponse(BaseModel):
    items: list[UpcomingRun]


# ── Schedule log ───────────────────────────────────────────────────────────


class ScheduleLogRead(BaseModel):
    id: int
    rule_id: int | None = None
    source_id: int | None = None
    job_id: int | None = None
    trigger_reason: str
    calculated_interval_minutes: float | None = None
    next_fetch_at: datetime | None = None
    fired_at: datetime

    model_config = {"from_attributes": True}


class ScheduleLogListResponse(BaseModel):
    items: list[ScheduleLogRead]
    total: int


# ── Recalculate ────────────────────────────────────────────────────────────


class RecalculateRequest(BaseModel):
    source_ids: list[int] | None = Field(None, description="Пересчитать только эти источники; None = все активные")


class RecalculateResponse(BaseModel):
    recalculated: int
    errors: int
    details: list[dict[str, Any]] = []


# ── Metrics ────────────────────────────────────────────────────────────────


class SchedulerMetrics(BaseModel):
    is_running: bool
    last_tick: datetime | None = None
    jobs_fired_total: int
    skipped_rate_limit: int
    skipped_night_mode: int
    firings_last_hour: int
    firings_last_24h: int
    rules_total: int
    rules_enabled: int


# ── Scheduler state ────────────────────────────────────────────────────────


class SchedulerState(BaseModel):
    is_running: bool
    last_tick: datetime | None = None
    jobs_fired_total: int
    skipped_rate_limit: int
    skipped_night_mode: int


# ── Due sources ────────────────────────────────────────────────────────────


class DueSourceItem(BaseModel):
    source_id: int
    name: str | None = None
    platform: str | None = None
    url: str
    next_fetch_at: datetime | None = None
    last_success_at: datetime | None = None
    error_count: int
    priority: int


class DueSourcesResponse(BaseModel):
    items: list[DueSourceItem]
    total: int


# ── Run-due ────────────────────────────────────────────────────────────────


class RunDueResponse(BaseModel):
    created: int
    skipped: int
    job_ids: list[int]
