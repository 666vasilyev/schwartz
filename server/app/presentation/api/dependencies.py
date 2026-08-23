from collections.abc import AsyncGenerator

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.auth.tokens import decode_access_token
from app.infrastructure.db.orm.models import User
from app.infrastructure.db.orm.session import get_db  # re-export for router injection
from app.infrastructure.repositories.user import get_user_by_id

__all__ = ["get_db", "get_session", "get_current_user"]

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a DB session."""
    async for session in get_db():
        yield session


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
    db: AsyncSession = Depends(get_session),
) -> User:
    """
    Декодирует access-JWT из заголовка `Authorization: Bearer <token>` и
    возвращает активного пользователя. Используется как router-level
    dependency почти на всех эндпоинтах (см. main.py/routes/*.py) — закрытые
    сейчас только /auth/login, /auth/refresh и /health.
    """
    unauthorized = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Требуется авторизация",
        headers={"WWW-Authenticate": "Bearer"},
    )
    if credentials is None or not credentials.credentials:
        raise unauthorized

    payload = decode_access_token(credentials.credentials)
    if payload is None:
        raise unauthorized

    try:
        user_id = int(payload.get("sub"))
    except (TypeError, ValueError):
        raise unauthorized

    user = await get_user_by_id(db, user_id)
    if user is None or not user.is_active:
        raise unauthorized

    return user
