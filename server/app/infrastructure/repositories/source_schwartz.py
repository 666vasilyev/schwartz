from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.schwartz_values import (
    SCHWARTZ_KEYS,
    normalize_schwartz_payload,
)
from app.infrastructure.db.orm.models import SourceSchwartzAnalysis


async def get_source_schwartz_by_source_id(
    db: AsyncSession, source_id: int
) -> SourceSchwartzAnalysis | None:
    r = await db.execute(
        select(SourceSchwartzAnalysis).where(
            SourceSchwartzAnalysis.source_id == source_id
        )
    )
    return r.scalar_one_or_none()


async def replace_source_schwartz(
    db: AsyncSession,
    source_id: int,
    values: dict[str, float],
) -> SourceSchwartzAnalysis:
    """Заменяет строку анализа Шварца для источника нормализованными средними."""
    await db.execute(
        delete(SourceSchwartzAnalysis).where(
            SourceSchwartzAnalysis.source_id == source_id
        )
    )
    await db.flush()
    norm = normalize_schwartz_payload(values)
    row = SourceSchwartzAnalysis(
        source_id=source_id,
        **{k: norm[k] for k in SCHWARTZ_KEYS},
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row
