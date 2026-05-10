"""Manually recalculate next_fetch_at for one or all active sources."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.scheduler.engine import calculate_next_fetch_at
from app.infrastructure.db.orm.models import Source, SourceStatus
from app.infrastructure.repositories.schedule import find_rule_for_source
from app.infrastructure.repositories.source import update_source
from app.presentation.schemas.schedule import RecalculateRequest, RecalculateResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def execute(db: AsyncSession, body: RecalculateRequest) -> RecalculateResponse:
    if body.source_ids:
        q = select(Source).where(
            Source.id.in_(body.source_ids),
            Source.deleted_at.is_(None),
        )
    else:
        q = select(Source).where(
            Source.deleted_at.is_(None),
            Source.status == SourceStatus.ACTIVE.value,
        )

    result = await db.execute(q)
    sources = list(result.scalars().all())

    recalculated = 0
    errors = 0
    details: list[dict] = []

    for src in sources:
        try:
            rule = await find_rule_for_source(db, src)
            next_at = calculate_next_fetch_at(src, rule)
            await update_source(db, src.id, next_fetch_at=next_at)
            recalculated += 1
            details.append({
                "source_id": src.id,
                "next_fetch_at": next_at.isoformat(),
                "rule_id": rule.id if rule else None,
            })
        except Exception as exc:
            errors += 1
            logger.warning("recalculate_error", source_id=src.id, error=str(exc))
            details.append({"source_id": src.id, "error": str(exc)})

    return RecalculateResponse(recalculated=recalculated, errors=errors, details=details)
