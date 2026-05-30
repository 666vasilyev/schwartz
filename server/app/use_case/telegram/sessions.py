"""CRUD + check use cases for Telegram sessions."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.telegram_session import (
    add_session,
    delete_session,
    get_active_session,
    get_session_by_id,
    list_sessions,
    update_session,
)
from app.infrastructure.telegram.client import check_session
from app.presentation.schemas.telegram import (
    TelegramSessionAddRequest,
    TelegramSessionCheckResponse,
    TelegramSessionListResponse,
    TelegramSessionRead,
    TelegramSessionUpdateRequest,
)


async def add(db: AsyncSession, body: TelegramSessionAddRequest) -> TelegramSessionRead:
    row = await add_session(
        db,
        api_id=body.api_id,
        api_hash=body.api_hash,
        session_string=body.session_string,
        phone=body.phone,
        note=body.note,
    )
    await db.commit()
    await db.refresh(row)
    return TelegramSessionRead.model_validate(row)


async def get_list(db: AsyncSession) -> TelegramSessionListResponse:
    rows = await list_sessions(db)
    items = [TelegramSessionRead.model_validate(r) for r in rows]
    return TelegramSessionListResponse(items=items, total=len(items))


async def get_one(db: AsyncSession, session_id: int) -> TelegramSessionRead:
    row = await get_session_by_id(db, session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    return TelegramSessionRead.model_validate(row)


async def update(
    db: AsyncSession, session_id: int, body: TelegramSessionUpdateRequest
) -> TelegramSessionRead:
    kwargs = body.model_dump(exclude_none=True)
    row = await update_session(db, session_id, **kwargs)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    await db.commit()
    await db.refresh(row)
    return TelegramSessionRead.model_validate(row)


async def remove(db: AsyncSession, session_id: int) -> None:
    ok = await delete_session(db, session_id)
    if not ok:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    await db.commit()


async def check(db: AsyncSession, session_id: int) -> TelegramSessionCheckResponse:
    row = await get_session_by_id(db, session_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Сессия не найдена")
    result = await check_session(row)
    return TelegramSessionCheckResponse(**result)


async def _require_active_session(db: AsyncSession):
    row = await get_active_session(db)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет активной Telegram-сессии. Добавьте сессию через POST /api/v1/telegram/sessions",
        )
    return row
