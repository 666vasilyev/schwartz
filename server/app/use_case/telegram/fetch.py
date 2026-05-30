"""Manual fetch use cases for Telegram sources."""
from __future__ import annotations

import re
from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Source
from app.infrastructure.repositories.post import get_post_by_source_and_external, save_post
from app.infrastructure.repositories.source import get_source_by_id, update_source
from app.infrastructure.repositories.telegram_session import get_active_session
from app.infrastructure.telegram.client import TelegramClientError, fetch_channel_posts, resolve_channel
from app.presentation.schemas.telegram import (
    TelegramFetchPreviewResponse,
    TelegramFetchRequest,
    TelegramFetchResult,
    TelegramResolveRequest,
    TelegramResolvedChannel,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TG_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})", re.IGNORECASE)


def _username_from_url(url: str) -> str:
    m = _TG_RE.search(url)
    return m.group(1) if m else url.lstrip("@").strip()


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


async def _require_tg_source(db: AsyncSession, source_id: int) -> Source:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    if src.source_type != "telegram":
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Источник не является Telegram-источником",
        )
    return src


async def _require_session(db: AsyncSession):
    session = await get_active_session(db)
    if session is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Нет активной Telegram-сессии. Добавьте через POST /api/v1/telegram/sessions",
        )
    return session


async def resolve(db: AsyncSession, body: TelegramResolveRequest) -> TelegramResolvedChannel:
    session = await _require_session(db)
    username = _username_from_url(body.url)
    try:
        info = await resolve_channel(session, username)
    except TelegramClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка Telegram: {exc}",
        ) from exc
    return TelegramResolvedChannel(
        username=username,
        canonical_url=f"https://t.me/{username}",
        **info,
    )


async def fetch(db: AsyncSession, source_id: int, body: TelegramFetchRequest) -> TelegramFetchResult:
    src = await _require_tg_source(db, source_id)
    session = await _require_session(db)
    username = _username_from_url(src.url)

    meta = dict(src.source_metadata or {})
    min_id = int(meta.get("last_tg_message_id", 0)) if not body.force_full else 0

    try:
        posts, max_id = await fetch_channel_posts(
            session, username, limit=body.limit, min_id=min_id
        )
    except TelegramClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка Telegram: {exc}",
        ) from exc

    saved = 0
    duplicate = 0
    async with db.begin_nested():
        for post in posts:
            ext = post["external_id"]
            existing = await get_post_by_source_and_external(db, src.id, ext)
            if existing:
                duplicate += 1
                continue
            await save_post(db, {
                "source_id": src.id,
                "external_id": ext,
                "text": post.get("text"),
                "published_at": datetime.fromisoformat(post["published_at"]) if post.get("published_at") else None,
                "reactions": post.get("reactions") or None,
                "payload": {
                    "views": post.get("views", 0),
                    "comments": post.get("comments", 0),
                    "media_urls": post.get("media_urls", []),
                    "is_forwarded": post.get("is_forwarded", False),
                },
            })
            saved += 1

    now = _utcnow()
    if max_id:
        meta["last_tg_message_id"] = max_id
    meta["total_collected"] = int(meta.get("total_collected", 0)) + saved
    await update_source(
        db, src.id,
        source_metadata=meta,
        last_fetch_at=now,
        last_success_at=now,
        error_count=0,
    )
    await db.commit()

    logger.info("telegram_fetch_done", source_id=source_id, fetched=len(posts), saved=saved)
    return TelegramFetchResult(
        source_id=source_id,
        username=username,
        fetched_count=len(posts),
        saved_count=saved,
        duplicate_count=duplicate,
        last_message_id=max_id,
    )


async def fetch_preview(
    db: AsyncSession, source_id: int, body: TelegramFetchRequest
) -> TelegramFetchPreviewResponse:
    src = await _require_tg_source(db, source_id)
    session = await _require_session(db)
    username = _username_from_url(src.url)

    try:
        posts, _ = await fetch_channel_posts(session, username, limit=body.limit, min_id=0)
    except TelegramClientError as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Ошибка Telegram: {exc}",
        ) from exc

    return TelegramFetchPreviewResponse(
        username=username,
        posts=posts,
        fetched_count=len(posts),
    )
