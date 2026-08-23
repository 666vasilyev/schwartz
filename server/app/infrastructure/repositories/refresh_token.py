from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import RefreshToken
from app.infrastructure.repositories.common import utcnow


async def create_refresh_token_record(
    db: AsyncSession, *, user_id: int, token_hash: str, expires_at: datetime
) -> RefreshToken:
    record = RefreshToken(user_id=user_id, token_hash=token_hash, expires_at=expires_at)
    db.add(record)
    await db.flush()
    await db.refresh(record)
    return record


async def get_refresh_token_by_hash(db: AsyncSession, token_hash: str) -> RefreshToken | None:
    """Не фильтрует по revoked_at/expires_at — эти проверки на стороне use_case
    (чтобы явно различать "не найден" от "найден, но истёк/отозван" в логике/логах)."""
    result = await db.execute(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
    return result.scalar_one_or_none()


async def revoke_refresh_token(db: AsyncSession, token_hash: str) -> bool:
    record = await get_refresh_token_by_hash(db, token_hash)
    if record is None or record.revoked_at is not None:
        return False
    record.revoked_at = utcnow()
    await db.flush()
    return True
