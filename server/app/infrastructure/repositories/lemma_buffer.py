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
    Если (user_id, lemma) уже есть — обновляем raw_text/источник (последнее
    место, где лемму выделили), first_seen_at не трогаем — порядок в буфере
    фиксируется первым выделением. Иначе создаём новую запись. Возвращает
    (запись, добавлена_ли_новая).
    """
    result = await db.execute(
        select(LemmaBufferEntry).where(
            LemmaBufferEntry.user_id == user_id, LemmaBufferEntry.lemma == lemma
        )
    )
    existing = result.scalar_one_or_none()
    if existing is not None:
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


async def set_buffer_weights(
    db: AsyncSession,
    *,
    user_id: int,
    lemma: str,
    weights: dict[str, float],
    category: str,
) -> bool:
    """
    Сохранить веса/категорию для уже существующей записи буфера (после
    LLM-генерации через GET /lemma/trend-candidates/{lemma}/weights или
    ручного ввода на фронте). False, если такой леммы нет в буфере
    пользователя — вызывающий код сам решает, что с этим делать (см.
    not_found в LemmaBufferActionResponse).
    """
    result = await db.execute(
        select(LemmaBufferEntry).where(
            LemmaBufferEntry.user_id == user_id, LemmaBufferEntry.lemma == lemma
        )
    )
    entry = result.scalar_one_or_none()
    if entry is None:
        return False
    entry.weights = weights
    entry.category = category
    await db.flush()
    return True


async def list_buffer_entries(
    db: AsyncSession,
    *,
    user_id: int,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> tuple[list[LemmaBufferEntry], int]:
    """Отсортировано по first_seen_at (первая выделенная лемма — первая в списке)."""
    base = select(LemmaBufferEntry).where(LemmaBufferEntry.user_id == user_id)
    if search and search.strip():
        base = base.where(LemmaBufferEntry.lemma.ilike(f"%{search.strip()}%"))

    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()

    q = base.order_by(LemmaBufferEntry.first_seen_at.asc()).offset(offset).limit(limit)
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
