"""GET /api/v1/posts — список постов с фильтрами."""
from __future__ import annotations

from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post
from app.infrastructure.repositories.post import count_posts, list_posts
from app.presentation.schemas.post import PostListResponse, PostRead


def _build_post_url(post: Post, source_type: str | None, source_url: str | None = None) -> str | None:
    if source_type == "vk" and post.owner_id and post.vk_post_id:
        return f"https://vk.com/wall{post.owner_id}_{post.vk_post_id}"
    if source_type == "rss" and post.external_id:
        return post.external_id if post.external_id.startswith("http") else None
    if source_type == "telegram" and post.external_id and source_url:
        # source_url is https://t.me/{username}
        base = source_url.rstrip("/")
        return f"{base}/{post.external_id}"
    return None


async def execute(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 20,
    search: str | None = None,
    source_ids: list[int] | None = None,
    category_names: list[str] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> PostListResponse:
    total = await count_posts(
        db,
        source_ids=source_ids,
        category_names=category_names,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    rows = await list_posts(
        db,
        skip=skip,
        limit=limit,
        source_ids=source_ids,
        category_names=category_names,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    items = []
    for post, source_type, source_url in rows:
        data = PostRead.model_validate(post)
        data.source_type = source_type
        data.url = _build_post_url(post, source_type, source_url)
        items.append(data)
    return PostListResponse(
        items=items,
        total=total,
        skip=skip,
        limit=limit,
    )
