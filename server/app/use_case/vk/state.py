"""Collection state: read and reset the VK cursor stored in source_metadata."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.source import get_source_by_id, update_source
from app.presentation.schemas.vk import VkCollectionState, VkStateResetResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def get_state(db: AsyncSession, source_id: int) -> VkCollectionState:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if src.platform != "vk":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Источник не является VK-источником",
        )
    meta = src.source_metadata or {}
    return VkCollectionState(
        source_id=source_id,
        owner_id=src.vk_owner_id,
        last_vk_post_id=meta.get("last_vk_post_id"),
        total_collected=meta.get("total_collected"),
        last_fetch_at=src.last_fetch_at,
        last_success_at=src.last_success_at,
        error_count=src.error_count,
        last_error_at=src.last_error_at,
    )


async def reset_state(db: AsyncSession, source_id: int) -> VkStateResetResponse:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if src.platform != "vk":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Источник не является VK-источником",
        )
    meta = dict(src.source_metadata or {})
    meta.pop("last_vk_post_id", None)
    meta.pop("total_collected", None)
    await update_source(db, source_id, source_metadata=meta, error_count=0)
    return VkStateResetResponse(source_id=source_id, reset=True)
