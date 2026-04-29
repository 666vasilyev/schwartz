from collections.abc import AsyncGenerator
from sqlalchemy.ext.asyncio import AsyncSession
from app.infrastructure.db.orm.session import get_db  # re-export for router injection

__all__ = ["get_db", "get_session"]


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session."""
    async for session in get_db():
        yield session
