from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import get_source_by_id, list_posts_by_source_id
from app.presentation.schemas.post import PostResponse
from app.utils.source_image import build_source_image_url, extract_post_own_image_url


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
    items = []
    for p in posts:
        data = PostResponse.model_validate(p, from_attributes=True)
        # Тот же fallback, что и в общей ленте /api/v1/posts — источник тут
        # уже загружен один раз выше, отдельный join не нужен.
        data.image_url = extract_post_own_image_url(p.attachments) or build_source_image_url(
            source_id, row.image_filename, row.image_updated_at
        )
        items.append(data)
    return {"items": items, "source_id": source_id, "skip": skip, "limit": limit}
