from __future__ import annotations

import re

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import SourceStatus

_OMIT = object()
from app.infrastructure.feeds.rss_url import normalize_rss_feed_url
from app.infrastructure.repositories import add_audit_log, get_source_by_id, update_source
from app.infrastructure.vk.vk_public_url import normalize_vk_url, public_path_segment_from_url
from app.presentation.schemas.source import SourceRead, SourceUpdateRequest
from app.use_case.sources import vk_resolve


async def execute(
    db: AsyncSession,
    source_id: int,
    body: SourceUpdateRequest,
) -> SourceRead:
    row = await get_source_by_id(db, source_id)
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        return SourceRead.model_validate(row)

    prev_schedule = row.fetch_interval_minutes
    prev_status = row.status

    if "url" in patch:
        if row.source_type == "rss":
            try:
                patch["url"] = normalize_rss_feed_url(patch["url"])
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
                ) from exc
        elif row.source_type == "telegram":
            m = re.search(
                r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})",
                patch["url"],
                re.IGNORECASE,
            )
            if m:
                patch["url"] = f"https://t.me/{m.group(1)}"
            # иначе оставляем как есть — не ломаем запрос
        else:
            try:
                norm = normalize_vk_url(patch["url"])
                segment = public_path_segment_from_url(norm)
                patch["url"] = norm
                if "vk_owner_id" not in patch:
                    patch["vk_owner_id"] = await vk_resolve.resolve_vk_owner_id(segment)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)
                ) from exc

    if "status" in patch and patch["status"] is not None:
        st = patch["status"]
        patch["status"] = st.value if isinstance(st, SourceStatus) else st
    if "source_type" in patch and patch["source_type"] is not None:
        st = patch["source_type"]
        patch["source_type"] = st.value if hasattr(st, "value") else st

    # category_names handled separately (relationship, not column)
    extra: dict = {}
    if "category_names" in patch:
        extra["category_names"] = patch.pop("category_names")
    else:
        patch.pop("category_names", None)
    updated = await update_source(db, source_id, **extra, **patch)
    assert updated is not None

    # Audit: schedule change
    if "fetch_interval_minutes" in patch and patch["fetch_interval_minutes"] != prev_schedule:
        await add_audit_log(
            db,
            source_id,
            "schedule_changed",
            previous={"fetch_interval_minutes": prev_schedule},
            changes={"fetch_interval_minutes": patch["fetch_interval_minutes"]},
        )

    # Audit: status change (handled by enable/pause/disable use cases for those flows)
    if "status" in patch and patch["status"] != prev_status:
        action = patch["status"]
        await add_audit_log(
            db,
            source_id,
            action,
            previous={"status": prev_status},
            changes={"status": patch["status"]},
        )

    # Audit: credentials change (auth_required toggled)
    if "auth_required" in patch:
        await add_audit_log(
            db,
            source_id,
            "credentials_changed",
            previous={"auth_required": row.auth_required},
            changes={"auth_required": patch["auth_required"]},
        )

    return SourceRead.model_validate(updated)
