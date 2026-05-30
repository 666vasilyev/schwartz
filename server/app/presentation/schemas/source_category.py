from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class SourceCategoryCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    description: str | None = None


class SourceCategoryUpdateRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=255)
    description: str | None = None


class SourceCategoryRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str | None = None
    created_at: datetime
    updated_at: datetime


class SourceCategoryListResponse(BaseModel):
    items: list[SourceCategoryRead]
    total: int
    skip: int
    limit: int
