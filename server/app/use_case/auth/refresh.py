"""
POST /auth/refresh — обмен refresh-токена на новую пару access+refresh.

Ротация: старый refresh-токен отзывается сразу же при использовании, новый
выдаётся взамен — один и тот же refresh-токен нельзя предъявить дважды. Если
токен скомпрометирован и злоумышленник использует его раньше легитимного
клиента, следующий запрос легитимного клиента с тем же (уже отозванным)
токеном получит 401 — сигнал, что пора логиниться заново и разбираться.
"""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.auth.tokens import (
    create_access_token,
    generate_refresh_token,
    hash_refresh_token,
)
from app.infrastructure.repositories.common import utcnow
from app.infrastructure.repositories.refresh_token import (
    create_refresh_token_record,
    get_refresh_token_by_hash,
    revoke_refresh_token,
)
from app.infrastructure.repositories.user import get_user_by_id
from app.presentation.schemas.auth import TokenResponse


async def execute(db: AsyncSession, *, refresh_token: str) -> TokenResponse:
    invalid = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED, detail="Невалидный или истёкший refresh-токен"
    )

    token_hash = hash_refresh_token(refresh_token)
    record = await get_refresh_token_by_hash(db, token_hash)
    if record is None or record.revoked_at is not None or record.expires_at < utcnow():
        raise invalid

    user = await get_user_by_id(db, record.user_id)
    if user is None or not user.is_active:
        raise invalid

    await revoke_refresh_token(db, token_hash)

    access_token = create_access_token(user_id=user.id, username=user.username)
    raw_refresh, new_hash, expires_at = generate_refresh_token()
    await create_refresh_token_record(db, user_id=user.id, token_hash=new_hash, expires_at=expires_at)

    return TokenResponse(access_token=access_token, refresh_token=raw_refresh)
