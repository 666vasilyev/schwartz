from datetime import datetime, timezone

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.db.orm.models import Source, SourceAuditLog, SourceCategoryModel, SourceStatus

_OMIT = object()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── Queries ────────────────────────────────────────────────────────────────


async def _load_categories(db: AsyncSession, category_names: list[str]) -> list[SourceCategoryModel]:
    if not category_names:
        return []
    res = await db.execute(
        select(SourceCategoryModel).where(SourceCategoryModel.name.in_(category_names))
    )
    return list(res.scalars().all())


async def add_source(
    db: AsyncSession,
    *,
    url: str,
    name: str | None = None,
    source_type: str | None = None,
    username: str | None = None,
    external_id: str | None = None,
    description: str | None = None,
    vk_owner_id: int | None = None,
    status: str = SourceStatus.ACTIVE.value,
    priority: int = 0,
    fetch_interval_minutes: int = 60,
    auth_required: bool = False,
    collection_policy: dict | None = None,
    content_policy: dict | None = None,
    media_policy: dict | None = None,
    language_hint: str | None = None,
    region_hint: str | None = None,
    topic_hint: str | None = None,
    owner_id: int | None = None,
    category_names: list[str] | None = None,
    extra: dict | None = None,
    source_metadata: dict | None = None,
) -> Source:
    row = Source(
        url=url,
        name=name,
        source_type=source_type,
        username=username,
        external_id=external_id or (str(vk_owner_id) if vk_owner_id else None),
        description=description,
        vk_owner_id=vk_owner_id,
        status=status,
        priority=priority,
        fetch_interval_minutes=fetch_interval_minutes,
        auth_required=auth_required,
        collection_policy=collection_policy,
        content_policy=content_policy,
        media_policy=media_policy,
        language_hint=language_hint,
        region_hint=region_hint,
        topic_hint=topic_hint,
        owner_id=owner_id,
        extra=extra,
        source_metadata=source_metadata,
    )
    if category_names:
        row.categories = await _load_categories(db, category_names)
    db.add(row)
    await db.flush()
    # Re-fetch with `categories` eagerly loaded (selectinload) instead of a bare
    # refresh(): refresh() expires/relies-on-lazy-load for relationships, and a
    # later *synchronous* access (e.g. Pydantic's SourceRead.model_validate(row))
    # would then try to lazy-load outside the async greenlet and raise
    # MissingGreenlet. selectinload guarantees `categories` is already populated
    # on the returned instance.
    result = await db.execute(
        select(Source).options(selectinload(Source.categories)).where(Source.id == row.id)
    )
    return result.scalar_one()


async def get_source_by_id(db: AsyncSession, source_id: int) -> Source | None:
    result = await db.execute(
        select(Source)
        .options(selectinload(Source.categories))
        .where(Source.id == source_id, Source.deleted_at.is_(None))
    )
    return result.scalar_one_or_none()


async def update_source(
    db: AsyncSession,
    source_id: int,
    *,
    name: str | None | object = _OMIT,
    url: str | object = _OMIT,
    status: str | object = _OMIT,
    source_type: str | None | object = _OMIT,
    username: str | None | object = _OMIT,
    external_id: str | None | object = _OMIT,
    description: str | None | object = _OMIT,
    priority: int | object = _OMIT,
    fetch_interval_minutes: int | object = _OMIT,
    last_fetch_at: datetime | None | object = _OMIT,
    next_fetch_at: datetime | None | object = _OMIT,
    last_success_at: datetime | None | object = _OMIT,
    last_error_at: datetime | None | object = _OMIT,
    error_count: int | object = _OMIT,
    auth_required: bool | object = _OMIT,
    collection_policy: dict | None | object = _OMIT,
    content_policy: dict | None | object = _OMIT,
    media_policy: dict | None | object = _OMIT,
    language_hint: str | None | object = _OMIT,
    region_hint: str | None | object = _OMIT,
    topic_hint: str | None | object = _OMIT,
    owner_id: int | None | object = _OMIT,
    category_names: list[str] | None | object = _OMIT,
    last_run_at: datetime | None | object = _OMIT,
    error_message: str | None | object = _OMIT,
    vk_owner_id: int | None | object = _OMIT,
    extra: dict | None | object = _OMIT,
    source_metadata: dict | None | object = _OMIT,
) -> Source | None:
    row = await get_source_by_id(db, source_id)
    if row is None:
        return None

    fields = {
        "name": name,
        "url": url,
        "status": status,
        "source_type": source_type,
        "username": username,
        "external_id": external_id,
        "description": description,
        "priority": priority,
        "fetch_interval_minutes": fetch_interval_minutes,
        "last_fetch_at": last_fetch_at,
        "next_fetch_at": next_fetch_at,
        "last_success_at": last_success_at,
        "last_error_at": last_error_at,
        "error_count": error_count,
        "auth_required": auth_required,
        "collection_policy": collection_policy,
        "content_policy": content_policy,
        "media_policy": media_policy,
        "language_hint": language_hint,
        "region_hint": region_hint,
        "topic_hint": topic_hint,
        "owner_id": owner_id,
        "last_run_at": last_run_at,
        "error_message": error_message,
        "vk_owner_id": vk_owner_id,
        "extra": extra,
        "source_metadata": source_metadata,
    }
    for attr, value in fields.items():
        if value is not _OMIT:
            setattr(row, attr, value)

    if category_names is not _OMIT and category_names is not None:
        row.categories = await _load_categories(db, category_names)
    elif category_names == []:
        row.categories = []

    await db.flush()
    # Bare refresh() expires the eagerly-loaded `categories` relationship; re-fetch
    # via get_source_by_id (selectinload) instead of refresh()+return row, same
    # reasoning as in add_source above.
    return await get_source_by_id(db, source_id)


async def soft_delete_source(db: AsyncSession, source_id: int) -> bool:
    row = await get_source_by_id(db, source_id)
    if row is None:
        return False
    row.deleted_at = _utcnow()
    row.status = SourceStatus.DELETED.value
    await db.flush()
    return True


async def delete_source(db: AsyncSession, source_id: int) -> bool:
    """Hard delete — используется только внутренне или для очистки."""
    result = await db.execute(select(Source).where(Source.id == source_id))
    row = result.scalar_one_or_none()
    if row is None:
        return False
    await db.delete(row)
    await db.flush()
    return True


async def count_sources(
    db: AsyncSession,
    *,
    search: str | None,
    status: str | None = None,
    source_type: str | None = None,
    owner_id: int | None = None,
    include_deleted: bool = False,
) -> int:
    q = select(func.count()).select_from(Source)
    if not include_deleted:
        q = q.where(Source.deleted_at.is_(None))
    if search and search.strip():
        pat = f"%{search.strip()}%"
        q = q.where(or_(Source.name.ilike(pat), Source.url.ilike(pat)))
    if status:
        q = q.where(Source.status == status)
    if source_type:
        q = q.where(Source.source_type == source_type)
    if owner_id is not None:
        q = q.where(Source.owner_id == owner_id)
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def list_sources(
    db: AsyncSession,
    *,
    skip: int,
    limit: int,
    search: str | None = None,
    status: str | None = None,
    source_type: str | None = None,
    owner_id: int | None = None,
    include_deleted: bool = False,
) -> list[Source]:
    q = select(Source).options(selectinload(Source.categories)).order_by(Source.id.desc())
    if not include_deleted:
        q = q.where(Source.deleted_at.is_(None))
    if search and search.strip():
        pat = f"%{search.strip()}%"
        q = q.where(or_(Source.name.ilike(pat), Source.url.ilike(pat)))
    if status:
        q = q.where(Source.status == status)
    if source_type:
        q = q.where(Source.source_type == source_type)
    if owner_id is not None:
        q = q.where(Source.owner_id == owner_id)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


# ── Status transitions ──────────────────────────────────────────────────────


async def set_source_status(
    db: AsyncSession,
    source_id: int,
    new_status: str,
    *,
    error_message: str | None = _OMIT,  # type: ignore[assignment]
    error_count_delta: int = 0,
) -> Source | None:
    row = await get_source_by_id(db, source_id)
    if row is None:
        return None
    row.status = new_status
    if error_message is not _OMIT:
        row.error_message = error_message  # type: ignore[assignment]
    if error_count_delta != 0:
        row.error_count = (row.error_count or 0) + error_count_delta
    await db.flush()
    return await get_source_by_id(db, source_id)


# ── Audit log ───────────────────────────────────────────────────────────────


async def add_audit_log(
    db: AsyncSession,
    source_id: int,
    action: str,
    *,
    actor_id: int | None = None,
    previous: dict | None = None,
    changes: dict | None = None,
) -> SourceAuditLog:
    entry = SourceAuditLog(
        source_id=source_id,
        action=action,
        actor_id=actor_id,
        previous=previous,
        changes=changes,
    )
    db.add(entry)
    await db.flush()
    return entry


async def list_audit_logs(
    db: AsyncSession,
    source_id: int,
    *,
    skip: int = 0,
    limit: int = 50,
) -> list[SourceAuditLog]:
    q = (
        select(SourceAuditLog)
        .where(SourceAuditLog.source_id == source_id)
        .order_by(SourceAuditLog.id.desc())
        .offset(skip)
        .limit(limit)
    )
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_audit_logs(db: AsyncSession, source_id: int) -> int:
    q = select(func.count()).select_from(SourceAuditLog).where(
        SourceAuditLog.source_id == source_id
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)
