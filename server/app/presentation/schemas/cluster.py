"""Схемы API для сюжетных кластеров."""
from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from app.presentation.schemas.post import PostRead


class ClusterRead(BaseModel):
    """Карточка сюжета без полного списка постов."""

    id: int
    title: str | None = None
    summary: str | None = None
    topics: list[str] | None = None
    status: str
    posts_count: int
    sources_count: int
    first_seen_at: datetime
    last_seen_at: datetime
    model_name: str

    model_config = {"from_attributes": True}


class ClusterListResponse(BaseModel):
    items: list[ClusterRead]
    total: int
    skip: int = Field(ge=0)
    limit: int = Field(ge=1, le=200)


class ClusterDetailResponse(BaseModel):
    """Сюжет вместе с постами (постраничной выдачей)."""

    cluster: ClusterRead
    posts: list[PostRead]
    posts_total: int
    posts_skip: int = Field(ge=0)
    posts_limit: int = Field(ge=1, le=200)


class ClusterFirstSource(BaseModel):
    """Первоисточник сюжета: кто и когда впервые опубликовал (по всем постам кластера)."""

    source_id: int | None = None
    source_name: str | None = None
    first_published_at: datetime | None = None


class TrendingClusterItem(BaseModel):
    cluster: ClusterRead
    posts_in_window: int
    sources_in_window: int
    first_source: ClusterFirstSource | None = Field(
        default=None,
        description="Источник и дата самого раннего поста кластера (первоисточник сюжета)",
    )


class TrendingClustersResponse(BaseModel):
    """
    Единый ответ трендов. source_ids/category_names эхом отдают, какие фильтры
    были применены (пустой список — фильтр не задавался): пустые оба — общие
    тренды по всем источникам; задан один — тренд по этому множеству (union
    внутри него); заданы оба — пересечение (AND) множеств.
    """

    items: list[TrendingClusterItem]
    window_hours: int
    min_posts: int
    source_ids: list[int] = Field(default_factory=list)
    category_names: list[str] = Field(default_factory=list)


class ClusterRunResponse(BaseModel):
    """Ответ ручного запуска одного тика кластеризации."""

    processed: int
    new_clusters: int
    extended_clusters: int
    skipped_empty_text: int
    archived_clusters: int


class ClusterRebuildResponse(BaseModel):
    """Ответ полной перестройки."""

    cleared_clusters: bool
    processed_batches: int
    total_processed: int
    total_new_clusters: int
    total_extended_clusters: int
