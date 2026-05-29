"""
ClusteringRunner: фоновая asyncio-задача, которая периодически догоняет
новые посты и кластеризует их (single-pass online).

Запускается в lifespan FastAPI рядом со scheduler / collection_worker.
Управляется флагом settings.clustering_enabled — на случай, если в окружении
не нужна модель эмбеддингов (например, для лёгких тестов).

Дизайн:
  • Один tick = вытаскиваем до `clustering_batch_size` постов без эмбеддинга,
    прогоняем через clusterer.cluster_posts_batch.
  • Между тиками — sleep `clustering_tick_seconds`.
  • Сессия БД своя на каждый тик (не висит между тиками).
  • Падения тика логируются, цикл не останавливается.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

from app.application.services.content.clusterer import cluster_unprocessed_posts
from app.core.config import get_settings
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()


class ClusteringRunner:
    def __init__(self) -> None:
        self._task: asyncio.Task | None = None
        self._is_running: bool = False
        self._last_tick_at: datetime | None = None
        self._ticks_total: int = 0
        self._processed_total: int = 0

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._task is not None:
            return
        if not settings.clustering_enabled:
            logger.info("clustering_runner_disabled")
            return
        self._is_running = True
        self._task = asyncio.create_task(self._loop(), name="clustering_runner")
        logger.info(
            "clustering_runner_started",
            tick_seconds=settings.clustering_tick_seconds,
            batch_size=settings.clustering_batch_size,
            model=settings.embedding_model_name,
        )

    async def stop(self) -> None:
        self._is_running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("clustering_runner_stopped")

    # ── State ──────────────────────────────────────────────────────────────

    def state(self) -> dict:
        return {
            "running": self._is_running,
            "last_tick_at": self._last_tick_at.isoformat() if self._last_tick_at else None,
            "ticks_total": self._ticks_total,
            "processed_total": self._processed_total,
            "model": settings.embedding_model_name,
        }

    # ── Internal loop ──────────────────────────────────────────────────────

    async def _loop(self) -> None:
        # Небольшая задержка на старте, чтобы дать БД/воркеру подняться
        await asyncio.sleep(5.0)
        while self._is_running:
            try:
                await self._tick()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("clustering_tick_failed", error=str(exc))
            await asyncio.sleep(settings.clustering_tick_seconds)

    async def _tick(self) -> None:
        self._last_tick_at = datetime.now(tz=timezone.utc)
        async with AsyncSessionLocal() as session:
            try:
                result = await cluster_unprocessed_posts(session)
                await session.commit()
            except Exception:
                await session.rollback()
                raise
        self._ticks_total += 1
        self._processed_total += result.processed
        if result.processed:
            logger.info(
                "clustering_tick_done",
                processed=result.processed,
                new_clusters=result.new_clusters,
                extended_clusters=result.extended_clusters,
                archived=result.archived_clusters,
            )


runner = ClusteringRunner()
