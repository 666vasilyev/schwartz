from __future__ import annotations

import httpx
from fastapi import HTTPException, status

from app.application.services.collect.rss_feed import collect_rss_items_for_ingest
from app.presentation.schemas.collector import RssCollectRequest, RssCollectResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def execute(body: RssCollectRequest) -> RssCollectResponse:
    try:
        norm_url, feed_title, items = await collect_rss_items_for_ingest(
            feed_url=body.url,
            limit=body.limit,
            use_mock=body.use_mock,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except httpx.HTTPStatusError as exc:
        logger.warning("rss_fetch_http_error", url=body.url, status=exc.response.status_code)
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Лента вернула HTTP {exc.response.status_code}",
        ) from exc
    except httpx.RequestError as exc:
        logger.error("rss_fetch_unreachable", url=body.url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Не удалось загрузить ленту: {exc!s}",
        ) from exc

    return RssCollectResponse(
        url=norm_url,
        feed_title=feed_title,
        collected=len(items),
        items=items,
        mock=body.use_mock,
    )
