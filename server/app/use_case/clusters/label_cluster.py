"""POST /api/v1/clusters/{id}/label — сгенерировать title/summary/topics через LLM."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.cluster_labeler import label_cluster
from app.infrastructure.repositories import get_cluster_by_id
from app.presentation.schemas.cluster import ClusterRead


async def execute(db: AsyncSession, cluster_id: int) -> ClusterRead:
    cluster = await get_cluster_by_id(db, cluster_id)
    if cluster is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Cluster id={cluster_id} not found",
        )
    ok = await label_cluster(db, cluster_id)
    if not ok:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="LLM не смог сгенерировать разметку (нет текстов или ошибка модели)",
        )
    # Перечитываем — labels уже обновлены
    refreshed = await get_cluster_by_id(db, cluster_id)
    assert refreshed is not None
    return ClusterRead.model_validate(refreshed)
