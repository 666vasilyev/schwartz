"""Telegram channel collector using Telethon (MTProto)."""
from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TG_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})",
    re.IGNORECASE,
)


def _parse_username(url_or_username: str) -> str:
    """Extract bare channel username from URL or @handle."""
    s = url_or_username.strip()
    m = _TG_RE.search(s)
    if m:
        return m.group(1)
    return s.lstrip("@")


async def collect_telegram_channel(
    url: str,
    limit: int = 20,
) -> tuple[str, str | None, list[dict[str, Any]]]:
    """
    Returns (canonical_url, channel_title, posts_list).
    Each post dict contains: external_id, text, published_at, views, reactions,
    comments, media_urls, is_forwarded.
    """
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise ValueError(
            "Telegram API не настроен: укажите TELEGRAM_API_ID и TELEGRAM_API_HASH"
        )

    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
        from telethon.tl.types import (
            MessageMediaDocument,
            MessageMediaPhoto,
            MessageReactions,
        )
    except ImportError as exc:
        raise ImportError(
            "Telethon не установлен. Добавьте telethon в requirements.txt клиента."
        ) from exc

    username = _parse_username(url)
    session = StringSession(settings.telegram_session_string or "")

    client = TelegramClient(session, settings.telegram_api_id, settings.telegram_api_hash)
    await client.connect()

    try:
        entity = await client.get_entity(username)
        channel_title: str | None = getattr(entity, "title", None)
        canonical_url = f"https://t.me/{username}"

        posts: list[dict[str, Any]] = []
        async for msg in client.iter_messages(entity, limit=limit):
            if not msg.date:
                continue

            # Media URLs
            media_urls: list[str] = []
            if isinstance(msg.media, MessageMediaPhoto):
                media_urls.append(f"tg://photo/{msg.id}")
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                if doc:
                    media_urls.append(f"tg://document/{doc.id}")

            # Reactions
            reactions: dict[str, int] = {}
            if msg.reactions and isinstance(msg.reactions, MessageReactions):
                for r in (msg.reactions.results or []):
                    emoji = getattr(r.reaction, "emoticon", "?")
                    reactions[emoji] = r.count

            posts.append(
                {
                    "external_id": str(msg.id),
                    "text": msg.message or "",
                    "published_at": msg.date.isoformat(),
                    "views": msg.views or 0,
                    "reactions": reactions,
                    "comments": msg.replies.replies if msg.replies else 0,
                    "media_urls": media_urls,
                    "is_forwarded": msg.fwd_from is not None,
                }
            )

        return canonical_url, channel_title, posts

    finally:
        await client.disconnect()
