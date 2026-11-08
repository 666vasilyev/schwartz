"""Обновление численности источников группы и запись снимков (динамика численности, метрика I.2)."""
from __future__ import annotations

from sqlalchemy import select

from app.infrastructure.db.orm.models import Source
from app.infrastructure.db.orm.models_vozd import SocialGroup, social_group_sources
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.db.project_scope import PROJECT_VOZD, use_project_scope
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _fetch_count(db, src: Source) -> int | None:
    if src.source_type == "vk":
        from app.presentation.schemas.vk import VkResolveRequest
        from app.use_case.vk.resolve import execute as vk_resolve

        resolved = await vk_resolve(VkResolveRequest(url=src.url))
        return resolved.members_count
    if src.source_type == "telegram" and src.username:
        from app.infrastructure.repositories.telegram_session import get_active_session
        from app.infrastructure.telegram.client import resolve_channel

        session = await get_active_session(db)
        if session is None:
            return None
        info = await resolve_channel(session, src.username)
        return info.get("participants_count")
    return None


async def refresh_members(group_id: int) -> int:
    """Запросить у VK/Telegram текущее число участников источников группы, обновить метаданные
    источников и записать снимок. Ошибка по одному источнику не мешает остальным. Возвращает число снимков."""
    from app.use_case.vozd.analytics.service import record_member_snapshots

    async with AsyncSessionLocal() as db:
        use_project_scope(db, PROJECT_VOZD)
        group = await db.get(SocialGroup, group_id)
        if group is None:
            return 0
        sources = list(
            (
                await db.execute(
                    select(Source)
                    .join(social_group_sources, social_group_sources.c.source_id == Source.id)
                    .where(social_group_sources.c.group_id == group_id, Source.deleted_at.is_(None))
                    .order_by(Source.id)
                )
            ).scalars()
        )
        for src in sources:
            try:
                count = await _fetch_count(db, src)
            except Exception as exc:  # noqa: BLE001
                logger.info("vozd_members_refresh_failed", source_id=src.id, error=str(exc)[:200])
                continue
            if isinstance(count, int) and count >= 0:
                src.source_metadata = {**(src.source_metadata or {}), "members_count": count}
        await db.commit()
        return await record_member_snapshots(db, group, sources)
