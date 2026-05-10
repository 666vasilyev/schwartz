from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.infrastructure.db.orm.models import JobStatus, JobType, TriggerType


# ── Requests ───────────────────────────────────────────────────────────────


class CreateJobRequest(BaseModel):
    source_id: int | None = Field(None, ge=1)
    job_type: JobType = JobType.MANUAL_FETCH
    trigger_type: TriggerType = TriggerType.API
    priority: int = Field(default=5, ge=1, le=10)
    requested_limit: int | None = Field(None, ge=1, le=10_000)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    correlation_id: str | None = Field(None, max_length=128)
    params: dict[str, Any] | None = None


class FetchRequest(BaseModel):
    """Request to start a collection job for a source."""
    limit: int = Field(default=100, ge=1, le=10_000)
    priority: int = Field(default=5, ge=1, le=10)
    max_retries: int = Field(default=3, ge=0, le=10)
    timeout_seconds: int = Field(default=300, ge=10, le=3600)
    correlation_id: str | None = None
    params: dict[str, Any] | None = None


class HistoricalFetchRequest(BaseModel):
    limit: int = Field(default=1000, ge=1, le=50_000)
    date_from: datetime | None = None
    date_to: datetime | None = None
    priority: int = Field(default=7, ge=1, le=10)
    correlation_id: str | None = None


class BulkFetchRequest(BaseModel):
    source_ids: list[int] = Field(..., min_length=1, max_length=100)
    limit: int = Field(default=100, ge=1, le=10_000)
    priority: int = Field(default=5, ge=1, le=10)


# ── Responses ──────────────────────────────────────────────────────────────


class JobRead(BaseModel):
    id: int
    source_id: int | None = None
    job_type: str
    status: str
    trigger_type: str
    priority: int
    started_at: datetime | None = None
    finished_at: datetime | None = None
    duration_ms: int | None = None
    requested_limit: int | None = None
    fetched_count: int = 0
    saved_count: int = 0
    duplicate_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    error_message: str | None = None
    error_code: str | None = None
    worker_id: str | None = None
    correlation_id: str | None = None
    retry_count: int = 0
    max_retries: int = 3
    next_retry_at: datetime | None = None
    timeout_seconds: int = 300
    params: dict | None = None
    result: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobListResponse(BaseModel):
    items: list[JobRead]
    total: int
    skip: int
    limit: int


class JobLogRead(BaseModel):
    id: int
    job_id: int
    level: str
    message: str
    data: dict | None = None
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class JobLogListResponse(BaseModel):
    items: list[JobLogRead]
    total: int
    skip: int
    limit: int


class JobResultResponse(BaseModel):
    job_id: int
    status: str
    result: dict | None = None
    fetched_count: int
    saved_count: int
    duplicate_count: int
    skipped_count: int
    failed_count: int
    duration_ms: int | None = None


# ── Queue / Worker state ───────────────────────────────────────────────────


class QueueStats(BaseModel):
    queued: int
    running: int
    created: int
    success: int
    failed: int
    cancelled: int
    timeout: int
    partial_success: int
    total_active: int


class WorkerState(BaseModel):
    worker_id: str
    running_jobs: int
    max_concurrent: int
    is_running: bool


class StuckJobsResponse(BaseModel):
    items: list[JobRead]
    total: int


class RecoverResponse(BaseModel):
    recovered_count: int
    job_ids: list[int]


class BulkFetchResponse(BaseModel):
    created: list[JobRead]
    errors: list[dict[str, Any]]
