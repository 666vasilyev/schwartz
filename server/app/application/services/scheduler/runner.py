"""
SchedulerService: background asyncio task that periodically fires collection jobs
for sources whose next_fetch_at <= now, respecting schedule rules and rate limits.
"""
from __future__ import annotations

import asyncio
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any

from app.application.services.scheduler.engine import calculate_next_fetch_at
from app.infrastructure.db.orm.models import JobType, SourceStatus, TriggerType
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.repositories.collection_job import (
    count_active_jobs_for_platform,
    count_active_jobs_for_source,
    create_job,
    find_due_sources,
)
from app.infrastructure.repositories.schedule import (
    add_schedule_log,
    find_rule_for_source,
)
from app.infrastructure.repositories.source import update_source
from app.utils.log_events import Events
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TICK_INTERVAL = 60.0  # seconds between scheduler ticks
_MAX_JOBS_PER_TICK = 20  # hard cap per tick to prevent bursts


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


class SchedulerService:
    """Singleton that fires collection jobs on a schedule."""

    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._is_running: bool = False
        self._last_tick: datetime | None = None
        self._jobs_fired_total: int = 0
        self._skipped_rate_limit: int = 0
        self._skipped_night_mode: int = 0
        # In-memory rate-limit buckets: platform → list of fired timestamps
        self._platform_buckets: dict[str, list[datetime]] = defaultdict(list)

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is not None:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._loop(), name="scheduler_service")
        logger.info(Events.SCHEDULER_TICK, message="Scheduler service started")

    async def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info(Events.WORKER_SHUTDOWN, message="Scheduler service stopped")

    # ── State ──────────────────────────────────────────────────────────────

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def jobs_fired_total(self) -> int:
        return self._jobs_fired_total

    def state(self) -> dict[str, Any]:
        return {
            "is_running": self._is_running,
            "last_tick": self._last_tick.isoformat() if self._last_tick else None,
            "jobs_fired_total": self._jobs_fired_total,
            "skipped_rate_limit": self._skipped_rate_limit,
            "skipped_night_mode": self._skipped_night_mode,
        }

    # ── Rate limiting ──────────────────────────────────────────────────────

    def _clean_bucket(self, platform: str) -> None:
        cutoff = _utcnow() - timedelta(hours=1)
        self._platform_buckets[platform] = [
            t for t in self._platform_buckets[platform] if t >= cutoff
        ]

    def _platform_jobs_last_hour(self, platform: str) -> int:
        self._clean_bucket(platform)
        return len(self._platform_buckets[platform])

    def _record_platform_fire(self, platform: str) -> None:
        self._clean_bucket(platform)
        self._platform_buckets[platform].append(_utcnow())

    # ── Main loop ──────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        while self._is_running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    Events.WORKER_UNEXPECTED_ERROR,
                    message=f"Scheduler tick error: {exc}",
                    error=str(exc),
                )
            try:
                await asyncio.sleep(_TICK_INTERVAL)
            except asyncio.CancelledError:
                break

    async def _tick(self) -> None:
        self._last_tick = _utcnow()
        fired = 0
        logger.debug(
            Events.SCHEDULER_TICK,
            message="Scheduler tick",
            jobs_fired_total=self._jobs_fired_total,
        )

        async with AsyncSessionLocal() as db:
            due_sources = await find_due_sources(db)
            if not due_sources:
                return

            for src in due_sources:
                if fired >= _MAX_JOBS_PER_TICK:
                    break

                rule = await find_rule_for_source(db, src)

                # Check if rule is disabled (explicit disable, not just absent)
                if rule is not None and not rule.is_enabled:
                    continue

                platform = src.source_type or "unknown"

                # Night mode check (rate-limit-style skip)
                if rule and rule.night_mode_enabled:
                    from app.application.services.scheduler.engine import _in_night_window
                    now_h = _utcnow().hour
                    if _in_night_window(now_h, rule.night_start_hour, rule.night_end_hour):
                        # Check if the interval was extended enough — if next_fetch_at
                        # is still in the future after adjustment, skip
                        pass  # The engine already extends the interval; just let it fire

                # Platform-level rate limit from rule
                max_jph = rule.max_jobs_per_hour if rule else 60
                if self._platform_jobs_last_hour(platform) >= max_jph:
                    self._skipped_rate_limit += 1
                    await add_schedule_log(
                        db,
                        rule_id=rule.id if rule else None,
                        source_id=src.id,
                        job_id=None,
                        trigger_reason="skipped_rate_limit",
                    )
                    continue

                # Per-source active job guard
                active = await count_active_jobs_for_source(db, src.id)
                if active > 0:
                    continue

                # Per-platform active job guard from rule
                max_concurrent = rule.max_concurrent_jobs if rule else 5
                platform_active = await count_active_jobs_for_platform(db, platform)
                if platform_active >= max_concurrent:
                    self._skipped_rate_limit += 1
                    continue

                # Create the job
                try:
                    job = await create_job(
                        db,
                        job_type=JobType.SCHEDULED_FETCH.value,
                        source_id=src.id,
                        trigger_type=TriggerType.SCHEDULER.value,
                        priority=src.priority or 5,
                    )

                    next_at = calculate_next_fetch_at(src, rule)
                    await update_source(db, src.id, next_fetch_at=next_at)

                    await add_schedule_log(
                        db,
                        rule_id=rule.id if rule else None,
                        source_id=src.id,
                        job_id=job.id,
                        trigger_reason="scheduled",
                        next_fetch_at=next_at,
                    )

                    self._record_platform_fire(platform)
                    self._jobs_fired_total += 1
                    fired += 1

                    logger.info(
                        Events.SCHEDULER_JOB_ENQUEUED,
                        message=f"Scheduled job {job.id} for source {src.id}",
                        source_id=src.id,
                        job_id=job.id,
                        platform=platform,
                        next_fetch_at=next_at.isoformat(),
                    )

                except Exception as exc:
                    logger.error(
                        Events.WORKER_UNEXPECTED_ERROR,
                        message=f"Failed to create scheduled job for source {src.id}",
                        source_id=src.id,
                        error=str(exc),
                    )
                    continue

            await db.commit()


# Global singleton — started/stopped via FastAPI lifespan
scheduler = SchedulerService()
