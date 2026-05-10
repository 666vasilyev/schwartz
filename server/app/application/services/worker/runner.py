"""
CollectionWorker: in-process async job worker.

- Polls collection_jobs WHERE status='queued' using SELECT FOR UPDATE SKIP LOCKED
- Respects per-worker concurrency limit (MAX_CONCURRENT)
- Manages asyncio task lifecycle
- Exposes state for /workers monitoring endpoint
"""
from __future__ import annotations

import asyncio
import os
import socket
import uuid
from datetime import datetime, timezone

from app.application.services.worker.executor import execute_job
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.repositories import pick_next_job
from app.utils.log_events import Events
from app.utils.logger import get_logger

logger = get_logger(__name__)

_POLL_INTERVAL = 5.0   # seconds between queue polls
_MAX_CONCURRENT = 5    # max simultaneous running jobs per worker
_HEARTBEAT_EVERY = 60  # log a heartbeat every N seconds


class CollectionWorker:
    """Singleton worker that runs as a background asyncio task."""

    def __init__(self) -> None:
        self.worker_id: str = _make_worker_id()
        self._task: asyncio.Task | None = None
        self._running_tasks: dict[int, asyncio.Task] = {}
        self._is_running: bool = False
        self._started_at: datetime | None = None
        self._last_heartbeat: float = 0.0

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is not None:
            return
        self._is_running = True
        self._started_at = datetime.now(tz=timezone.utc)
        self._task = asyncio.create_task(self._loop(), name="collection_worker")
        logger.info(
            Events.COLLECTION_JOB_QUEUED,
            message=f"Worker {self.worker_id} started",
            worker_id=self.worker_id,
        )

    async def stop(self) -> None:
        self._is_running = False
        logger.info(
            Events.WORKER_SHUTDOWN,
            message=f"Worker {self.worker_id} shutting down",
            worker_id=self.worker_id,
            active_jobs=len(self._running_tasks),
        )
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None

        for job_id, task in list(self._running_tasks.items()):
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._running_tasks.clear()

    # ── State ──────────────────────────────────────────────────────────────

    @property
    def running_jobs(self) -> int:
        return len(self._running_tasks)

    @property
    def max_concurrent(self) -> int:
        return _MAX_CONCURRENT

    @property
    def is_running(self) -> bool:
        return self._is_running

    # ── Main loop ──────────────────────────────────────────────────────────

    async def _loop(self) -> None:
        import time

        while self._is_running:
            try:
                done = [jid for jid, t in self._running_tasks.items() if t.done()]
                for jid in done:
                    self._running_tasks.pop(jid, None)

                now = time.monotonic()
                if now - self._last_heartbeat >= _HEARTBEAT_EVERY:
                    logger.debug(
                        Events.WORKER_HEARTBEAT,
                        message="Worker heartbeat",
                        worker_id=self.worker_id,
                        active_jobs=len(self._running_tasks),
                        max_concurrent=_MAX_CONCURRENT,
                    )
                    self._last_heartbeat = now

                if len(self._running_tasks) >= _MAX_CONCURRENT:
                    await asyncio.sleep(_POLL_INTERVAL)
                    continue

                picked = await self._try_pick_job()
                if picked is None:
                    await asyncio.sleep(_POLL_INTERVAL)
                else:
                    await asyncio.sleep(0.1)

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error(
                    Events.WORKER_UNEXPECTED_ERROR,
                    message=f"Worker loop error: {exc}",
                    worker_id=self.worker_id,
                    error=str(exc),
                )
                await asyncio.sleep(_POLL_INTERVAL)

    async def _try_pick_job(self) -> int | None:
        async with AsyncSessionLocal() as db:
            try:
                job = await pick_next_job(db, self.worker_id)
                if job is None:
                    return None
                job_id = job.id
                await db.commit()
            except Exception as exc:
                logger.error(
                    Events.WORKER_UNEXPECTED_ERROR,
                    message="Failed to pick job from queue",
                    worker_id=self.worker_id,
                    error=str(exc),
                )
                await db.rollback()
                return None

        task = asyncio.create_task(self._run_job(job_id), name=f"job_{job_id}")
        self._running_tasks[job_id] = task
        return job_id

    async def _run_job(self, job_id: int) -> None:
        async with AsyncSessionLocal() as db:
            try:
                await execute_job(db, job_id, self.worker_id)
            except Exception as exc:
                logger.error(
                    Events.WORKER_UNEXPECTED_ERROR,
                    message=f"Unhandled error in job {job_id}",
                    job_id=job_id,
                    worker_id=self.worker_id,
                    error=str(exc),
                )
                await db.rollback()
            finally:
                self._running_tasks.pop(job_id, None)


def _make_worker_id() -> str:
    hostname = socket.gethostname()
    pid = os.getpid()
    uid = uuid.uuid4().hex[:8]
    return f"{hostname}:{pid}:{uid}"


# Global singleton — started/stopped via FastAPI lifespan
worker = CollectionWorker()
