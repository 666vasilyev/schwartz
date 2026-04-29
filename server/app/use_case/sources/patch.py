from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import SourceStatus
from app.infrastructure.feeds.rss_url import normalize_rss_feed_url
from app.infrastructure.repositories import get_source_by_id, update_source
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
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Источник не найден",
        )

    patch = body.model_dump(exclude_unset=True)
    if not patch:
        return SourceRead.model_validate(row)

    if "url" in patch:
        if row.source == "rss":
            try:
                patch["url"] = normalize_rss_feed_url(patch["url"])
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc
        else:
            try:
                norm = normalize_vk_url(patch["url"])
                segment = public_path_segment_from_url(norm)
                patch["url"] = norm
                if "vk_owner_id" not in patch:
                    patch["vk_owner_id"] = await vk_resolve.resolve_vk_owner_id(segment)
            except ValueError as exc:
                raise HTTPException(
                    status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                    detail=str(exc),
                ) from exc

    if "status" in patch and patch["status"] is not None:
        st = patch["status"]
        patch["status"] = st.value if isinstance(st, SourceStatus) else st

    kw: dict = {}
    if "name" in patch:
        kw["name"] = patch["name"]
    if "url" in patch:
        kw["url"] = patch["url"]
    if "status" in patch:
        kw["status"] = patch["status"]
    if "vk_owner_id" in patch:
        kw["vk_owner_id"] = patch["vk_owner_id"]
    if "error_message" in patch:
        kw["error_message"] = patch["error_message"]
    if "last_run_at" in patch:
        kw["last_run_at"] = patch["last_run_at"]

    updated = await update_source(db, source_id, **kw)
    assert updated is not None
    return SourceRead.model_validate(updated)
