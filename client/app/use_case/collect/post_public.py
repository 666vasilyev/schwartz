from __future__ import annotations

from fastapi import HTTPException, status
from tenacity import RetryError

from app.application.services.collect.public_wall import (
    collect_public_posts_for_ingest,
    resolve_wall_owner_id,
)
from app.infrastructure.vk.client import VKApiError
from app.infrastructure.vk.vk_public_url import (
    normalize_vk_url,
    public_path_segment_from_url,
)
from app.presentation.schemas.collector import PublicCollectRequest, PublicCollectResponse


async def execute(body: PublicCollectRequest) -> PublicCollectResponse:
    try:
        norm_url = normalize_vk_url(body.url)
        segment = public_path_segment_from_url(norm_url)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(e),
        ) from e

    if body.use_mock:
        owner_id = -1
    else:
        try:
            owner_id = await resolve_wall_owner_id(segment)
        except Exception as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Не удалось определить стену: {exc!s}",
            ) from exc

    try:
        posts = await collect_public_posts_for_ingest(
            owner_id=owner_id,
            limit=body.limit,
            use_mock=body.use_mock,
        )
    except VKApiError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except RetryError as exc:
        cause = exc.last_attempt.exception()
        detail = str(cause) if cause else str(exc)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=detail,
        ) from exc

    return PublicCollectResponse(
        url=norm_url,
        vk_owner_id=owner_id,
        collected=len(posts),
        posts=posts,
        mock=body.use_mock,
    )
