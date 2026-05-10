"""Scheduler metrics use case."""
from __future__ import annotations

from datetime import timedelta, timezone
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.scheduler.runner import scheduler
from app.infrastructure.repositories.schedule import (
    count_rules,
    count_schedule_logs_since,
)
from app.presentation.schemas.schedule import SchedulerMetrics, SchedulerState


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def get_metrics(db: AsyncSession) -> SchedulerMetrics:
    now = _utcnow()
    state = scheduler.state()

    firings_1h = await count_schedule_logs_since(db, now - timedelta(hours=1))
    firings_24h = await count_schedule_logs_since(db, now - timedelta(hours=24))
    rules_total = await count_rules(db)
    rules_enabled = await count_rules(db, is_enabled=True)

    last_tick = None
    if state.get("last_tick"):
        try:
            last_tick = datetime.fromisoformat(state["last_tick"])
        except ValueError:
            pass

    return SchedulerMetrics(
        is_running=state["is_running"],
        last_tick=last_tick,
        jobs_fired_total=state["jobs_fired_total"],
        skipped_rate_limit=state["skipped_rate_limit"],
        skipped_night_mode=state["skipped_night_mode"],
        firings_last_hour=firings_1h,
        firings_last_24h=firings_24h,
        rules_total=rules_total,
        rules_enabled=rules_enabled,
    )


def get_state() -> SchedulerState:
    state = scheduler.state()
    last_tick = None
    if state.get("last_tick"):
        try:
            last_tick = datetime.fromisoformat(state["last_tick"])
        except ValueError:
            pass
    return SchedulerState(
        is_running=state["is_running"],
        last_tick=last_tick,
        jobs_fired_total=state["jobs_fired_total"],
        skipped_rate_limit=state["skipped_rate_limit"],
        skipped_night_mode=state["skipped_night_mode"],
    )
