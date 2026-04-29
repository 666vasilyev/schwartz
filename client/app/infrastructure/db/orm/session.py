"""Пул Postgres для ротации токенов VK (таблица vk_access_tokens, миграции на сервере)."""

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.core.config import get_settings

settings = get_settings()

engine = create_async_engine(
    settings.ASYNC_DATABASE_URL,
    echo=not settings.is_production,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=10,
)


class Base(DeclarativeBase):
    pass


AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autocommit=False,
    autoflush=False,
)
