"""
Фоновый воркер проекта vozd: берёт прогоны из vozd_runs по одному.

Отдельный от CollectionWorker wall — очередь collection_jobs не затрагивается,
долгие прогоны «воздействия» не задерживают плановый сбор wall.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select, update

from app.application.services.vozd.collector import execute_run
from app.infrastructure.db.orm.models_vozd import RunStatus, VozdRun
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)

_POLL_INTERVAL = 5.0


class VozdRunner:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._current: int | None = None
        self._is_running = False

    def start(self) -> None:
        if self._task is not None:
            return
        self._is_running = True
        self._task = asyncio.create_task(self._loop(), name="vozd_runner")

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
        return {"is_running": self._is_running, "current_run_id": self._current}

    async def _recover(self) -> None:
        """После рестарта прогоны, оставшиеся в running, возвращаются в очередь (продолжат с чекпойнта)."""
        async with AsyncSessionLocal() as db:
            await db.execute(
                update(VozdRun).where(VozdRun.status == RunStatus.RUNNING).values(status=RunStatus.QUEUED)
            )
            await db.commit()

    async def _pick(self) -> int | None:
        async with AsyncSessionLocal() as db:
            run = (
                await db.execute(
                    select(VozdRun)
                    .where(VozdRun.status == RunStatus.QUEUED)
                    .order_by(VozdRun.id)
                    .limit(1)
                    .with_for_update(skip_locked=True)
                )
            ).scalar_one_or_none()
            if run is None:
                return None
            run.status = RunStatus.RUNNING
            run.started_at = run.started_at or datetime.now(tz=timezone.utc)
            run.heartbeat_at = datetime.now(tz=timezone.utc)
            await db.commit()
            return run.id

    async def _loop(self) -> None:
        try:
            await self._recover()
        except Exception as exc:  # noqa: BLE001
            logger.error("vozd_recover_failed", error=str(exc)[:300])
        while self._is_running:
            try:
                run_id = await self._pick()
                if run_id is None:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue
                self._current = run_id
                logger.info("vozd_run_started", run_id=run_id)
                await execute_run(run_id)
                self._current = None
            except asyncio.CancelledError:
                break
            except Exception as exc:  # noqa: BLE001
                self._current = None
                logger.error("vozd_runner_error", error=str(exc)[:300])
                await asyncio.sleep(_POLL_INTERVAL)


runner = VozdRunner()
