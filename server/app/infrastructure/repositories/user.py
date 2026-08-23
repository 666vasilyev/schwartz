from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import User


async def get_user_by_username(db: AsyncSession, username: str) -> User | None:
    result = await db.execute(select(User).where(User.username == username))
    return result.scalar_one_or_none()


async def get_user_by_id(db: AsyncSession, user_id: int) -> User | None:
    result = await db.execute(select(User).where(User.id == user_id))
    return result.scalar_one_or_none()


async def create_user(db: AsyncSession, *, username: str, hashed_password: str) -> User:
    """Используется только scripts/create_user.py — нет HTTP-ручки регистрации."""
    user = User(username=username, hashed_password=hashed_password)
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user
