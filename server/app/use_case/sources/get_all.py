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
    source_type: str | None = None,
    owner_id: int | None = None,
    sort_by: str | None = None,
    sort_dir: str = "asc",
    sort_value: str | None = None,
) -> SourceListResponse:
    total = await count_sources(
        db, search=q, status=status, source_type=source_type, owner_id=owner_id
    )
    rows = await fetch_sources(
        db,
        skip=skip,
        limit=limit,
        search=q,
        status=status,
        source_type=source_type,
        owner_id=owner_id,
        sort_by=sort_by,
        sort_dir=sort_dir,
        sort_value=sort_value,
    )
    return SourceListResponse(
        items=[SourceRead.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
