from __future__ import annotations

import re
from urllib.parse import urlparse

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import JobType, SourceStatus, TriggerType
from app.infrastructure.feeds.rss_url import normalize_rss_feed_url
from app.infrastructure.repositories import add_source
from app.infrastructure.repositories.collection_job import create_job
from app.infrastructure.repositories.source_category import get_category
from psycopg.errors import UniqueViolation
from sqlalchemy.exc import IntegrityError
from app.infrastructure.vk.vk_public_url import normalize_vk_url, public_path_segment_from_url
from app.presentation.schemas.source import SourceCreateRequest, SourceRead
from app.use_case.sources import vk_resolve
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def _enqueue_initial_fetch(db: AsyncSession, source_id: int) -> None:
    try:
        await create_job(
            db,
            job_type=JobType.MANUAL_FETCH.value,
            source_id=source_id,
            trigger_type=TriggerType.SYSTEM.value,
            priority=5,
            requested_limit=20,
            params={"limit": 20},
        )
    except Exception as exc:
        logger.warning("initial_fetch_enqueue_failed", source_id=source_id, error=str(exc))


async def _validate_category_ids(db: AsyncSession, category_ids: list[int]) -> None:
    for cid in category_ids:
        obj = await get_category(db, cid)
        if not obj:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Категория с id={cid} не найдена",
            )


async def execute(db: AsyncSession, body: SourceCreateRequest) -> SourceRead:
    category_ids = body.category_ids or []
    await _validate_category_ids(db, category_ids)

    try:
        url_lower = body.url.lower()
        is_telegram = (body.source_type and body.source_type.value == "telegram") or (
            not body.source_type
            and ("t.me/" in url_lower or "telegram.me/" in url_lower)
        )
        is_rss = not is_telegram and (
            (body.source_type and body.source_type.value == "rss")
            or (not body.source_type and "vk.com" not in url_lower)
        )

        if is_telegram:
            m = re.search(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})", body.url, re.IGNORECASE)
            username = m.group(1) if m else body.url.lstrip("@").strip()
            norm = f"https://t.me/{username}"
            display_name = body.name if body.name and body.name.strip() else f"@{username}"
            row = await add_source(
                db,
                url=norm,
                name=display_name,
                source_type="telegram",
                username=username,
                external_id=username,
                description=body.description,
                status=SourceStatus.ACTIVE.value,
                priority=body.priority,
                fetch_interval_minutes=body.fetch_interval_minutes,
                auth_required=body.auth_required,
                collection_policy=body.collection_policy,
                content_policy=body.content_policy,
                media_policy=body.media_policy,
                language_hint=body.language_hint,
                region_hint=body.region_hint,
                topic_hint=body.topic_hint,
                owner_id=body.owner_id,
                category_ids=category_ids,
            )
            logger.info("source_registered_telegram", source_id=row.id, url=norm)
            await _enqueue_initial_fetch(db, row.id)
            return SourceRead.model_validate(row)

        if is_rss:
            try:
                norm = normalize_rss_feed_url(body.url)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
            p = urlparse(norm)
            fallback = (p.path or "").strip("/").split("/")[0] or p.netloc or norm
            display_name = body.name if body.name and body.name.strip() else fallback
            row = await add_source(
                db,
                url=norm,
                name=display_name,
                source_type="rss",
                description=body.description,
                status=SourceStatus.ACTIVE.value,
                priority=body.priority,
                fetch_interval_minutes=body.fetch_interval_minutes,
                auth_required=body.auth_required,
                collection_policy=body.collection_policy,
                content_policy=body.content_policy,
                media_policy=body.media_policy,
                language_hint=body.language_hint,
                region_hint=body.region_hint,
                topic_hint=body.topic_hint,
                owner_id=body.owner_id,
                category_ids=category_ids,
            )
            logger.info("source_registered_rss", source_id=row.id, url=norm)
            await _enqueue_initial_fetch(db, row.id)
            return SourceRead.model_validate(row)

        try:
            norm = normalize_vk_url(body.url)
            segment = public_path_segment_from_url(norm)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=str(exc),
            ) from exc
        display_name = body.name if body.name and body.name.strip() else segment
        vk_owner_id = await vk_resolve.resolve_vk_owner_id(segment)
        row = await add_source(
            db,
            url=norm,
            name=display_name,
            source_type="vk",
            username=segment,
            external_id=str(vk_owner_id) if vk_owner_id else None,
            vk_owner_id=vk_owner_id,
            description=body.description,
            status=SourceStatus.ACTIVE.value,
            priority=body.priority,
            fetch_interval_minutes=body.fetch_interval_minutes,
            auth_required=body.auth_required,
            collection_policy=body.collection_policy,
            content_policy=body.content_policy,
            media_policy=body.media_policy,
            language_hint=body.language_hint,
            region_hint=body.region_hint,
            topic_hint=body.topic_hint,
            owner_id=body.owner_id,
            category_ids=category_ids,
        )
        logger.info("source_registered", source_id=row.id, url=norm, vk_owner_id=vk_owner_id)
        await _enqueue_initial_fetch(db, row.id)
        return SourceRead.model_validate(row)

    except IntegrityError as exc:
        if isinstance(exc.orig, UniqueViolation):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="Источник с таким URL или external_id уже существует",
            ) from exc
        raise
