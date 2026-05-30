"""Use case: collect posts from a Telegram channel."""
from __future__ import annotations

from fastapi import HTTPException, status

from app.application.services.collect.telegram_channel import collect_telegram_channel
from app.presentation.schemas.collector import TelegramCollectRequest, TelegramCollectResponse
from app.utils.logger import get_logger

logger = get_logger(__name__)


async def execute(body: TelegramCollectRequest) -> TelegramCollectResponse:
    try:
        canonical_url, channel_title, posts = await collect_telegram_channel(
            url=body.url,
            limit=body.limit,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_501_NOT_IMPLEMENTED,
            detail=str(exc),
        ) from exc
    except Exception as exc:
        logger.error("telegram_collect_error", url=body.url, error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка сбора Telegram: {exc!s}",
        ) from exc

    return TelegramCollectResponse(
        url=canonical_url,
        channel_title=channel_title,
        collected=len(posts),
        posts=posts,
    )
