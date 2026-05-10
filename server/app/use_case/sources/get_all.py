from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import count_sources, list_sources as fetch_sources
from app.presentation.schemas.source import SourceListResponse, SourceRead


async def execute(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    q: str | None,
    status: str | None = None,
    platform: str | None = None,
    source_type: str | None = None,
    owner_id: int | None = None,
) -> SourceListResponse:
    total = await count_sources(
        db, search=q, status=status, platform=platform, source_type=source_type, owner_id=owner_id
    )
    rows = await fetch_sources(
        db,
        skip=skip,
        limit=limit,
        search=q,
        status=status,
        platform=platform,
        source_type=source_type,
        owner_id=owner_id,
    )
    return SourceListResponse(
        items=[SourceRead.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
