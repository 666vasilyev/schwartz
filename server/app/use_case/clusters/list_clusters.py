"""GET /api/v1/clusters — список сюжетов с фильтрами."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import StoryClusterStatus
from app.infrastructure.repositories import count_clusters, list_clusters
from app.presentation.schemas.cluster import ClusterListResponse, ClusterRead


async def execute(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    status: str | None,
    min_posts: int | None,
    date_from: datetime | None,
    date_to: datetime | None,
) -> ClusterListResponse:
    effective_status = status or StoryClusterStatus.ACTIVE.value
    items = await list_clusters(
        db,
        skip=skip,
        limit=limit,
        status=effective_status,
        min_posts=min_posts,
        date_from=date_from,
        date_to=date_to,
    )
    total = await count_clusters(
        db,
        status=effective_status,
        min_posts=min_posts,
        date_from=date_from,
        date_to=date_to,
    )
    return ClusterListResponse(
        items=[ClusterRead.model_validate(c) for c in items],
        total=total,
        skip=skip,
        limit=limit,
    )
