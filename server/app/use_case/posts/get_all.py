"""GET /api/v1/posts — список постов с фильтрами."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.post import count_posts, list_posts
from app.presentation.schemas.post import PostListResponse, PostRead


async def execute(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    source_id: int | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    category: str | None = None,
) -> PostListResponse:
    total = await count_posts(
        db,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        category=category,
    )
    rows = await list_posts(
        db,
        skip=skip,
        limit=limit,
        source_id=source_id,
        date_from=date_from,
        date_to=date_to,
        category=category,
    )
    return PostListResponse(
        items=[PostRead.model_validate(r) for r in rows],
        total=total,
        skip=skip,
        limit=limit,
    )
