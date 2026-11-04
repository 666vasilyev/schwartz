"""
Планировщик автосбора проекта vozd.

Раз в минуту берёт группы с включённым расписанием, у которых наступил next_run_at, и ставит для них
прогон в очередь vozd_runs (его выполняет VozdRunner). Если у группы уже идёт прогон (ручной или прошлый
плановый) или в ней нет источников, запуск пропускается, а next_run_at сдвигается на следующий интервал.
Планировщик «Стены» эту таблицу не затрагивает.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, or_, select

from app.core.config import get_settings
from app.infrastructure.db.orm.models_vozd import (
    RunStage,
    RunStatus,
    SocialGroup,
    VozdRun,
    social_group_sources,
)
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.db.project_scope import PROJECT_VOZD, use_project_scope
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


class VozdScheduler:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._is_running = False
        self._last_tick: datetime | None = None
        self._runs_created = 0
        self._skipped_busy = 0

    def start(self) -> None:
        if self._task is not None:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._loop(), name="vozd_scheduler")

    async def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

    def state(self) -> dict[str, Any]:
        return {
            "is_running": self._is_running,
            "last_tick": self._last_tick.isoformat() if self._last_tick else None,
            "runs_created": self._runs_created,
            "skipped_busy": self._skipped_busy,
        }

    async def _loop(self) -> None:
        tick = get_settings().vozd_scheduler_tick_seconds
        while self._is_running:
            try:
                await self.tick()
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                logger.error("vozd_scheduler_error", error=str(exc)[:300])
            try:
                await asyncio.sleep(tick)
            except asyncio.CancelledError:
                break

    async def tick(self) -> int:
        """Один проход планировщика; возвращает число созданных прогонов."""
        self._last_tick = now = _now()
        created = 0
        refresh_default = get_settings().vozd_comments_refresh_days_default
        async with AsyncSessionLocal() as db:
            use_project_scope(db, PROJECT_VOZD)
            groups = list(
                (
                    await db.execute(
                        select(SocialGroup)
                        .where(
                            SocialGroup.deleted_at.is_(None),
                            SocialGroup.schedule_enabled.is_(True),
                            or_(SocialGroup.next_run_at.is_(None), SocialGroup.next_run_at <= now),
                        )
                        .order_by(SocialGroup.next_run_at.asc().nulls_first(), SocialGroup.id)
                        .with_for_update(skip_locked=True)
                    )
                ).scalars()
            )
            for g in groups:
                interval = timedelta(hours=max(1, g.schedule_interval_hours or 24))
                g.next_run_at = now + interval
                busy = (
                    await db.execute(
                        select(VozdRun.id).where(
                            VozdRun.group_id == g.id,
                            VozdRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING]),
                        )
                    )
                ).first()
                if busy is not None:
                    self._skipped_busy += 1
                    logger.info("vozd_schedule_skipped_busy", group_id=g.id, active_run_id=busy[0])
                    continue
                n_sources = (
                    await db.execute(
                        select(func.count()).select_from(social_group_sources).where(
                            social_group_sources.c.group_id == g.id
                        )
                    )
                ).scalar_one()
                if not n_sources:
                    logger.info("vozd_schedule_skipped_empty", group_id=g.id)
                    continue
                params = {"trigger": "schedule"}
                if (g.params or {}).get("comments_refresh_days") is None:
                    params["comments_refresh_days"] = refresh_default
                run = VozdRun(
                    group_id=g.id, status=RunStatus.QUEUED, stage=RunStage.POSTS, params=params, progress={}
                )
                db.add(run)
                g.last_scheduled_run_at = now
                created += 1
                self._runs_created += 1
                logger.info("vozd_schedule_run_created", group_id=g.id)
            await db.commit()
        return created


vozd_scheduler = VozdScheduler()
