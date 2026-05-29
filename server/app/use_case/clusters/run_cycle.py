"""POST /api/v1/clusters/run — один цикл инкрементальной кластеризации."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.clusterer import cluster_unprocessed_posts
from app.presentation.schemas.cluster import ClusterRunResponse


async def execute(db: AsyncSession) -> ClusterRunResponse:
    result = await cluster_unprocessed_posts(db)
    return ClusterRunResponse(
        processed=result.processed,
        new_clusters=result.new_clusters,
        extended_clusters=result.extended_clusters,
        skipped_empty_text=result.skipped_empty_text,
        archived_clusters=result.archived_clusters,
    )
