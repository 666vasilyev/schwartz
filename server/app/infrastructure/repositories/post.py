from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post


async def get_post_by_vk_id(db: AsyncSession, vk_post_id: str) -> Post | None:
    result = await db.execute(select(Post).where(Post.vk_post_id == vk_post_id))
    return result.scalar_one_or_none()


async def get_post_by_source_and_external(
    db: AsyncSession, source_id: int, external_id: str
) -> Post | None:
    result = await db.execute(
        select(Post).where(
            Post.source_id == source_id,
            Post.external_id == external_id,
        )
    )
    return result.scalar_one_or_none()


async def save_post(db: AsyncSession, post_data: dict) -> Post:
    """Insert a post. Дедуп: (source_id, external_id) или глобально по vk_post_id."""
    source_id = post_data.get("source_id")
    external_id = post_data.get("external_id")
    if source_id is not None and external_id:
        existing = await get_post_by_source_and_external(db, source_id, external_id)
        if existing:
            return existing
    vk_post_id = post_data.get("vk_post_id")
    if vk_post_id:
        existing = await get_post_by_vk_id(db, vk_post_id)
        if existing:
            return existing
    post = Post(**post_data)
    db.add(post)
    await db.flush()
    await db.refresh(post)
    return post


async def get_post_by_id(db: AsyncSession, post_id: int) -> Post | None:
    result = await db.execute(select(Post).where(Post.id == post_id))
    return result.scalar_one_or_none()


async def get_recent_posts(db: AsyncSession, limit: int) -> list[Post]:
    if limit < 1:
        return []
    result = await db.execute(select(Post).order_by(Post.id.desc()).limit(limit))
    return list(result.scalars().all())


async def list_posts_by_owner_id(db: AsyncSession, owner_id: int) -> list[Post]:
    """Посты стены, совпадающие с vk_owner_id источника."""
    result = await db.execute(
        select(Post)
        .where(Post.owner_id == owner_id)
        .order_by(Post.id.asc())
    )
    return list(result.scalars().all())


async def list_posts_by_source_id(db: AsyncSession, source_id: int) -> list[Post]:
    """Посты, привязанные к источнику (RSS и т.д.)."""
    result = await db.execute(
        select(Post)
        .where(Post.source_id == source_id)
        .order_by(Post.id.asc())
    )
    return list(result.scalars().all())
