"""POST /auth/logout — отозвать refresh-токен (access-токен stateless, просто истечёт сам)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.auth.tokens import hash_refresh_token
from app.infrastructure.repositories.refresh_token import revoke_refresh_token


async def execute(db: AsyncSession, *, refresh_token: str) -> bool:
    return await revoke_refresh_token(db, hash_refresh_token(refresh_token))
