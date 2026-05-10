from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id, list_posts_by_source_id
from app.presentation.schemas.post import PostResponse


async def execute(
    db: AsyncSession,
    source_id: int,
    *,
    skip: int = 0,
    limit: int = 20,
) -> dict:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    posts = await list_posts_by_source_id(db, source_id, skip=skip, limit=limit)
    items = [PostResponse.model_validate(p, from_attributes=True) for p in posts]
    return {"items": items, "source_id": source_id, "skip": skip, "limit": limit}
