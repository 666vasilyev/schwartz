"""GET /api/v1/clusters/{id} — детали сюжета + посты."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import (
    count_posts_in_cluster,
    get_cluster_by_id,
    list_posts_in_cluster,
)
from app.presentation.schemas.cluster import ClusterDetailResponse, ClusterRead
from app.presentation.schemas.post import PostRead


async def execute(
    db: AsyncSession,
    cluster_id: int,
    *,
    posts_skip: int,
    posts_limit: int,
) -> ClusterDetailResponse:
    cluster = await get_cluster_by_id(db, cluster_id)
    if cluster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cluster id={cluster_id} not found",
        )
    posts = await list_posts_in_cluster(
        db, cluster_id, skip=posts_skip, limit=posts_limit
    )
    posts_total = await count_posts_in_cluster(db, cluster_id)
    return ClusterDetailResponse(
        cluster=ClusterRead.model_validate(cluster),
        posts=[PostRead.model_validate(p) for p in posts],
        posts_total=posts_total,
        posts_skip=posts_skip,
        posts_limit=posts_limit,
    )
