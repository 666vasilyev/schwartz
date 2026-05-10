"""
Токены VK только из БД: строка с минимальным usage + атомарный инкремент при вызове API.
"""
from __future__ import annotations

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import VkAccessToken
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PICK_INCREMENT = text(
    """
WITH cand AS (
  SELECT id FROM vk_access_tokens
  WHERE is_active = true
  ORDER BY usage ASC
  LIMIT 1
  FOR UPDATE SKIP LOCKED
)
UPDATE vk_access_tokens AS t
SET usage = t.usage + 1,
    last_used_at = (TIMEZONE('UTC', NOW()))
FROM cand
WHERE t.id = cand.id
RETURNING t.access_token AS access_token
"""
)


async def pick_and_increment_usage(session: AsyncSession) -> str | None:
    """Выбрать наименее использованный токен и увеличить usage на 1 (одна строка RETURNING)."""
    result = await session.execute(_PICK_INCREMENT)
    row = result.mappings().first()
    if row is None:
        return None
    return str(row["access_token"]).strip()


async def count_active_vk_tokens(session: AsyncSession) -> int:
    q = select(func.count()).select_from(VkAccessToken).where(VkAccessToken.is_active.is_(True))
    r = await session.execute(q)
    return int(r.scalar_one())


async def vk_token_sources_configured_async() -> bool:
    try:
        async with AsyncSessionLocal() as session:
            n = await count_active_vk_tokens(session)
            return n > 0
    except SQLAlchemyError:
        return False


async def acquire_vk_access_token() -> str | None:
    """Строка access_token из активной строки таблицы vk_access_tokens (+1 к usage в той же операции)."""
    try:
        async with AsyncSessionLocal() as session:
            picked = await pick_and_increment_usage(session)
            await session.commit()
            return picked
    except SQLAlchemyError as exc:
        logger.warning("vk_db_token_pick_failed", error=str(exc))
        return None


async def add_token(session: AsyncSession, access_token: str) -> VkAccessToken:
    token = VkAccessToken(access_token=access_token.strip(), is_active=True)
    session.add(token)
    await session.flush()
    return token


async def get_token_by_id(session: AsyncSession, token_id: int) -> VkAccessToken | None:
    result = await session.get(VkAccessToken, token_id)
    return result


async def list_tokens(session: AsyncSession) -> list[VkAccessToken]:
    q = select(VkAccessToken).order_by(VkAccessToken.created_at.desc())
    result = await session.execute(q)
    return list(result.scalars().all())


async def deactivate_token(session: AsyncSession, token_id: int) -> bool:
    token = await get_token_by_id(session, token_id)
    if token is None:
        return False
    token.is_active = False
    await session.flush()
    return True


async def activate_token(session: AsyncSession, token_id: int) -> bool:
    token = await get_token_by_id(session, token_id)
    if token is None:
        return False
    token.is_active = True
    await session.flush()
    return True
