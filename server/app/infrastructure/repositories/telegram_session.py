"""CRUD for TelegramSession."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import TelegramSession


async def add_session(
    db: AsyncSession,
    *,
    api_id: int,
    api_hash: str,
    session_string: str,
    phone: str | None = None,
    note: str | None = None,
) -> TelegramSession:
    row = TelegramSession(
        api_id=api_id,
        api_hash=api_hash,
        session_string=session_string,
        phone=phone,
        note=note,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_session_by_id(db: AsyncSession, session_id: int) -> TelegramSession | None:
    result = await db.execute(
        select(TelegramSession).where(TelegramSession.id == session_id)
    )
    return result.scalar_one_or_none()


async def list_sessions(db: AsyncSession) -> list[TelegramSession]:
    result = await db.execute(
        select(TelegramSession).order_by(TelegramSession.id.asc())
    )
    return list(result.scalars().all())


async def get_active_session(db: AsyncSession) -> TelegramSession | None:
    """Return first active session (round-robin logic can be added later)."""
    result = await db.execute(
        select(TelegramSession)
        .where(TelegramSession.is_active == True)  # noqa: E712
        .order_by(TelegramSession.id.asc())
        .limit(1)
    )
    return result.scalar_one_or_none()


async def update_session(
    db: AsyncSession,
    session_id: int,
    **kwargs,
) -> TelegramSession | None:
    row = await get_session_by_id(db, session_id)
    if row is None:
        return None
    for key, value in kwargs.items():
        if hasattr(row, key):
            setattr(row, key, value)
    await db.flush()
    await db.refresh(row)
    return row


async def delete_session(db: AsyncSession, session_id: int) -> bool:
    row = await get_session_by_id(db, session_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True
