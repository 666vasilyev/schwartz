from __future__ import annotations

from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import SourceStatus
from app.infrastructure.feeds.rss_url import normalize_rss_feed_url
from app.infrastructure.repositories import add_source
from app.infrastructure.vk.vk_public_url import normalize_vk_url, public_path_segment_from_url
from app.presentation.schemas.source import SourceCreateRequest, SourceRead
from app.use_case.sources import vk_resolve
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def execute(db: AsyncSession, body: SourceCreateRequest) -> SourceRead:
    if body.source == "rss":
        try:
            norm = normalize_rss_feed_url(body.url)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        p = urlparse(norm)
        fallback = (p.path or "").strip("/").split("/")[0] or p.netloc or norm
        display_name = body.name if body.name and body.name.strip() else fallback
        row = await add_source(
            db,
            url=norm,
            name=display_name,
            source="rss",
            vk_owner_id=None,
            status=SourceStatus.IDLE.value,
        )
        logger.info("source_registered_rss", source_id=row.id, url=norm)
        return SourceRead.model_validate(row)

    try:
        norm = normalize_vk_url(body.url)
        segment = public_path_segment_from_url(norm)
        display_name = body.name if body.name and body.name.strip() else segment
        vk_owner_id = await vk_resolve.resolve_vk_owner_id(segment)
        row = await add_source(
            db,
            url=norm,
            name=display_name,
            source="vk",
            vk_owner_id=vk_owner_id,
            status=SourceStatus.IDLE.value,
        )
        logger.info(
            "source_registered",
            source_id=row.id,
            url=norm,
            vk_owner_id=vk_owner_id,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    return SourceRead.model_validate(row)
