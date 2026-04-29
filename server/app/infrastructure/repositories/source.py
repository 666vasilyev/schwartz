from datetime import datetime

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Source, SourceStatus

_OMIT = object()


async def add_source(
    db: AsyncSession,
    *,
    url: str,
    name: str | None = None,
    source: str = "vk",
    vk_owner_id: int | None = None,
    status: str = SourceStatus.RUNNING.value,
    extra: dict | None = None,
) -> Source:
    row = Source(
        url=url,
        name=name,
        source=source,
        vk_owner_id=vk_owner_id,
        status=status,
        extra=extra,
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_source_by_id(db: AsyncSession, source_id: int) -> Source | None:
    result = await db.execute(select(Source).where(Source.id == source_id))
    return result.scalar_one_or_none()


async def update_source(
    db: AsyncSession,
    source_id: int,
    *,
    name: str | None | object = _OMIT,
    url: str | object = _OMIT,
    status: str | object = _OMIT,
    last_run_at: datetime | None | object = _OMIT,
    error_message: str | None | object = _OMIT,
    vk_owner_id: int | None | object = _OMIT,
    extra: dict | None | object = _OMIT,
) -> Source | None:
    row = await get_source_by_id(db, source_id)
    if row is None:
        return None
    if name is not _OMIT:
        row.name = name  # type: ignore[assignment]
    if url is not _OMIT:
        row.url = url  # type: ignore[assignment]
    if status is not _OMIT:
        row.status = status  # type: ignore[assignment]
    if last_run_at is not _OMIT:
        row.last_run_at = last_run_at  # type: ignore[assignment]
    if error_message is not _OMIT:
        row.error_message = error_message  # type: ignore[assignment]
    if vk_owner_id is not _OMIT:
        row.vk_owner_id = vk_owner_id  # type: ignore[assignment]
    if extra is not _OMIT:
        row.extra = extra  # type: ignore[assignment]
    await db.flush()
    await db.refresh(row)
    return row


async def delete_source(db: AsyncSession, source_id: int) -> bool:
    row = await get_source_by_id(db, source_id)
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def count_sources(db: AsyncSession, *, search: str | None) -> int:
    q = select(func.count()).select_from(Source)
    if search and search.strip():
        pat = f"%{search.strip()}%"
        q = q.where(
            or_(
                Source.name.ilike(pat),
                Source.url.ilike(pat),
            )
        )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def list_sources(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    search: str | None = None,
) -> list[Source]:
    q = select(Source).order_by(Source.id.desc())
    if search and search.strip():
        pat = f"%{search.strip()}%"
        q = q.where(
            or_(
                Source.name.ilike(pat),
                Source.url.ilike(pat),
            )
        )
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())
