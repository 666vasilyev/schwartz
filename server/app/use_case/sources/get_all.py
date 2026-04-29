from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import count_sources, list_sources as fetch_sources
from app.presentation.schemas.source import SourceListResponse, SourceRead


async def execute(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    q: str | None,
) -> SourceListResponse:
    total = await count_sources(db, search=q)
    rows = await fetch_sources(db, skip=skip, limit=limit, search=q)
    return SourceListResponse(
        items=[SourceRead.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
