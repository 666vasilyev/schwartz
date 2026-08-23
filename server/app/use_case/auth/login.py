"""
POST /auth/login — проверка логина/пароля, выдача пары access+refresh токенов.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.auth.password import verify_password
from app.application.services.auth.tokens import create_access_token, generate_refresh_token
from app.infrastructure.repositories.refresh_token import create_refresh_token_record
from app.infrastructure.repositories.user import get_user_by_username
from app.presentation.schemas.auth import TokenResponse


async def execute(db: AsyncSession, *, username: str, password: str) -> TokenResponse:
    user = await get_user_by_username(db, username)
    # Намеренно один и тот же ответ и для "нет такого username", и для "пароль
    # неверный" — иначе ручка становится оракулом для перебора существующих логинов.
    invalid = HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный логин или пароль")
    if user is None or not verify_password(password, user.hashed_password):
        raise invalid
    if not user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Учётная запись отключена")

    access_token = create_access_token(user_id=user.id, username=user.username)
    raw_refresh, refresh_hash, expires_at = generate_refresh_token()
    await create_refresh_token_record(db, user_id=user.id, token_hash=refresh_hash, expires_at=expires_at)

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)
