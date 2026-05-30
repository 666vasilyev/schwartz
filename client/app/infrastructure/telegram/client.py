"""Telethon client factory for the collector service."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncGenerator
from urllib.parse import urlparse

from app.core.config import get_settings


class TelegramClientError(Exception):
    pass


def _build_proxy(proxy_url: str) -> tuple | None:
    """
    Convert proxy URL (e.g. socks5://host:1080) to PySocks tuple for Telethon.
    Returns None if proxy_url is empty or PySocks is not installed.
    """
    if not proxy_url:
        return None
    try:
        import socks
    except ImportError:
        return None

    p = urlparse(proxy_url)
    scheme = (p.scheme or "").lower()
    host = p.hostname or "127.0.0.1"
    port = p.port or 1080
    username = p.username or None
    password = p.password or None

    proxy_type = socks.SOCKS5
    if scheme in ("socks4", "socks4a"):
        proxy_type = socks.SOCKS4
    elif scheme in ("http", "https"):
        proxy_type = socks.HTTP

    if username:
        return (proxy_type, host, port, True, username, password)
    return (proxy_type, host, port)


@asynccontextmanager
async def telegram_client(
    api_id: int,
    api_hash: str,
    session_string: str,
) -> AsyncGenerator[Any, None]:
    """
    Yields a connected Telethon TelegramClient routed through proxy.

    Usage:
        async with telegram_client(api_id, api_hash, session_string) as client:
            entity = await client.get_entity(username)
    """
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError as exc:
        raise TelegramClientError(
            "telethon не установлен. Добавьте telethon в requirements.txt"
        ) from exc

    settings = get_settings()
    proxy = _build_proxy(settings.proxy)

    client = TelegramClient(
        StringSession(session_string),
        api_id,
        api_hash,
        proxy=proxy,
    )
    await client.connect()
    try:
        yield client
    finally:
        await client.disconnect()


async def collect_channel_posts(
    api_id: int,
    api_hash: str,
    session_string: str,
    username: str,
    limit: int = 20,
) -> tuple[str, str | None, list[dict[str, Any]]]:
    """
    Collect posts from a Telegram channel.
    Returns (canonical_url, channel_title, posts).
    """
    try:
        from telethon.tl.types import (
            MessageMediaDocument,
            MessageMediaPhoto,
            MessageReactions,
        )
    except ImportError as exc:
        raise TelegramClientError("telethon не установлен") from exc

    canonical_url = f"https://t.me/{username}"
    channel_title: str | None = None
    posts: list[dict[str, Any]] = []

    async with telegram_client(api_id, api_hash, session_string) as client:
        entity = await client.get_entity(username)
        channel_title = getattr(entity, "title", None)

        async for msg in client.iter_messages(entity, limit=limit):
            if not msg.date:
                continue

            media_urls: list[str] = []
            if isinstance(msg.media, MessageMediaPhoto):
                media_urls.append(f"tg://photo/{msg.id}")
            elif isinstance(msg.media, MessageMediaDocument):
                doc = msg.media.document
                if doc:
                    media_urls.append(f"tg://document/{doc.id}")

            reactions: dict[str, int] = {}
            if msg.reactions and isinstance(msg.reactions, MessageReactions):
                for r in (msg.reactions.results or []):
                    emoji = getattr(r.reaction, "emoticon", "?")
                    reactions[emoji] = r.count

            posts.append({
                "external_id": str(msg.id),
                "text": msg.message or "",
                "published_at": msg.date.isoformat(),
                "views": msg.views or 0,
                "reactions": reactions,
                "comments": msg.replies.replies if msg.replies else 0,
                "media_urls": media_urls,
                "is_forwarded": msg.fwd_from is not None,
            })

    return canonical_url, channel_title, posts
