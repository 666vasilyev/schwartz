"""
POST /auth/login   — логин по username+password, выдаёт access+refresh токены.
POST /auth/refresh — обмен refresh-токена на новую пару (с ротацией).
POST /auth/logout  — отозвать refresh-токен.
GET  /auth/me      — текущий пользователь (по access-токену).

Регистрация закрытая: пользователей создаёт только scripts/create_user.py —
здесь намеренно нет POST /auth/register (нет ролей, только один уровень
доступа — "авторизован/нет" — так что открытая саморегистрация была бы
равносильна полностью открытому API).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import User
from app.presentation.api.dependencies import get_current_user, get_session
from app.presentation.schemas.auth import (
    LoginRequest,
    LogoutRequest,
    RefreshRequest,
    TokenResponse,
    UserRead,
)
from app.use_case.auth import login as login_uc
from app.use_case.auth import logout as logout_uc
from app.use_case.auth import refresh as refresh_uc

router = APIRouter(prefix="/auth", tags=["Auth"])


@router.post("/login", response_model=TokenResponse, summary="Логин по username+password")
async def login(body: LoginRequest, db: AsyncSession = Depends(get_session)) -> TokenResponse:
    return await login_uc.execute(db, username=body.username, password=body.password)


@router.post(
    "/refresh",
    response_model=TokenResponse,
    summary="Обновить access-токен по refresh-токену (с ротацией)",
)
async def refresh(body: RefreshRequest, db: AsyncSession = Depends(get_session)) -> TokenResponse:
    return await refresh_uc.execute(db, refresh_token=body.refresh_token)


@router.post("/logout", summary="Отозвать refresh-токен")
async def logout(body: LogoutRequest, db: AsyncSession = Depends(get_session)) -> dict:
    # Намеренно без Depends(get_current_user): logout должен работать и когда
    # access-токен уже истёк, но refresh ещё валиден — сам refresh-токен уже
    # достаточное доказательство личности для его собственного отзыва.
    revoked = await logout_uc.execute(db, refresh_token=body.refresh_token)
    return {"revoked": revoked}


@router.get("/me", response_model=UserRead, summary="Текущий пользователь (по access-токену)")
async def me(current_user: User = Depends(get_current_user)) -> UserRead:
    return UserRead.model_validate(current_user)
