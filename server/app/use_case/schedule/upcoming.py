"""Preview upcoming scheduled runs for active sources."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.scheduler.engine import calculate_interval, preview_upcoming
from app.infrastructure.db.orm.models import Source, SourceStatus
from app.infrastructure.repositories.schedule import find_rule_for_source
from app.presentation.schemas.schedule import UpcomingRun, UpcomingRunsResponse


async def execute(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    limit_sources: int = 20,
    runs_per_source: int = 5,
) -> UpcomingRunsResponse:
    if source_id is not None:
        q = select(Source).where(
            Source.id == source_id,
            Source.deleted_at.is_(None),
            Source.status == SourceStatus.ACTIVE.value,
        )
    else:
        q = (
            select(Source)
            .where(
                Source.deleted_at.is_(None),
                Source.status == SourceStatus.ACTIVE.value,
            )
            .order_by(Source.next_fetch_at.asc().nulls_first())
            .limit(limit_sources)
        )

    result = await db.execute(q)
    sources = list(result.scalars().all())

    runs: list[UpcomingRun] = []
    for src in sources:
        rule = await find_rule_for_source(db, src)
        timestamps = preview_upcoming(src, rule, count=runs_per_source)
        for ts in timestamps:
            interval = calculate_interval(src, rule)
            runs.append(
                UpcomingRun(
                    source_id=src.id,
                    source_name=src.name,
                    rule_id=rule.id if rule else None,
                    scheduled_at=ts,
                    calculated_interval_minutes=round(interval, 2),
                )
            )

    runs.sort(key=lambda r: r.scheduled_at)
    return UpcomingRunsResponse(items=runs)
