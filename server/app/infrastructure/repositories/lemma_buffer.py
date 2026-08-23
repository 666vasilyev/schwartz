"""
Репозиторий буфера лемм — персональные (per-user) кандидаты, выделенные на
фронте при чтении постов/трендов. См. докстринг LemmaBufferEntry в models.py.
"""
from __future__ import annotations

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import LemmaBufferEntry


async def upsert_buffer_entry(
    db: AsyncSession,
    *,
    user_id: int,
    lemma: str,
    raw_text: str,
    source_post_id: int | None = None,
    source_cluster_id: int | None = None,
) -> tuple[LemmaBufferEntry, bool]:
    """
    Если (user_id, lemma) уже есть — инкремент times_selected + обновление
    raw_text/источника (last_seen_at обновляется автоматически через onupdate),
    иначе новая запись. Возвращает (запись, добавлена_ли_новая).
    """
    result = await db.execute(
        select(LemmaBufferEntry).where(
            LemmaBufferEntry.user_id == user_id, LemmaBufferEntry.lemma == lemma
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
        existing.times_selected += 1
        existing.raw_text = raw_text
        if source_post_id is not None:
            existing.source_post_id = source_post_id
        if source_cluster_id is not None:
            existing.source_cluster_id = source_cluster_id
        await db.flush()
        return existing, False

    entry = LemmaBufferEntry(
        user_id=user_id,
        lemma=lemma,
        raw_text=raw_text,
        source_post_id=source_post_id,
        source_cluster_id=source_cluster_id,
    )
    db.add(entry)
    await db.flush()
    await db.refresh(entry)
    return entry, True


async def list_buffer_entries(
    db: AsyncSession,
    *,
    user_id: int,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LemmaBufferEntry], int]:
    """Отсортировано по times_selected (убыв.), затем last_seen_at (убыв.)."""
    base = select(LemmaBufferEntry).where(LemmaBufferEntry.user_id == user_id)
    if search and search.strip():
        base = base.where(LemmaBufferEntry.lemma.ilike(f"%{search.strip()}%"))

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    q = base.order_by(
        LemmaBufferEntry.times_selected.desc(), LemmaBufferEntry.last_seen_at.desc()
    ).offset(offset).limit(limit)
    rows = (await db.execute(q)).scalars().all()
    return list(rows), int(total)


async def remove_buffer_entries(db: AsyncSession, *, user_id: int, lemmas: list[str]) -> int:
    if not lemmas:
        return 0
    result = await db.execute(
        delete(LemmaBufferEntry).where(
            LemmaBufferEntry.user_id == user_id, LemmaBufferEntry.lemma.in_(lemmas)
        )
    )
    return result.rowcount or 0


async def clear_buffer(db: AsyncSession, *, user_id: int) -> int:
    result = await db.execute(delete(LemmaBufferEntry).where(LemmaBufferEntry.user_id == user_id))
    return result.rowcount or 0
