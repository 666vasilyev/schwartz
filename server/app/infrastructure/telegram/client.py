"""Telethon client factory — uses TelegramSession from DB."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any

from app.infrastructure.db.orm.models import TelegramSession


class TelegramClientError(Exception):
    pass


class NoActiveTelegramSession(TelegramClientError):
    pass


@asynccontextmanager
async def telegram_client(session: TelegramSession) -> AsyncGenerator[Any, None]:
    """
    Yields a connected Telethon TelegramClient.
    Usage:
        async with telegram_client(session) as client:
            entity = await client.get_entity(...)
    """
    try:
        from telethon import TelegramClient
        from telethon.sessions import StringSession
    except ImportError as exc:
        raise TelegramClientError(
            "telethon не установлен. Добавьте telethon в requirements.txt"
        ) from exc

    client = TelegramClient(
        StringSession(session.session_string),
        session.api_id,
        session.api_hash,
    )
    await client.connect()
    try:
        yield client
    finally:
        await client.disconnect()


async def check_session(session: TelegramSession) -> dict[str, Any]:
    """Verify that a session can connect and is authorized."""
    try:
        async with telegram_client(session) as client:
            authorized = await client.is_user_authorized()
            if not authorized:
                return {"valid": False, "reason": "Сессия не авторизована"}
            me = await client.get_me()
            return {
                "valid": True,
                "user_id": me.id if me else None,
                "username": getattr(me, "username", None),
                "phone": getattr(me, "phone", None),
                "first_name": getattr(me, "first_name", None),
            }
    except TelegramClientError as exc:
        return {"valid": False, "reason": str(exc)}
    except Exception as exc:
        return {"valid": False, "reason": f"{type(exc).__name__}: {exc}"}


async def resolve_channel(session: TelegramSession, username: str) -> dict[str, Any]:
    """Get channel/group info by username."""
    async with telegram_client(session) as client:
        entity = await client.get_entity(username)
        return {
            "id": entity.id,
            "title": getattr(entity, "title", None),
            "username": getattr(entity, "username", None),
            "participants_count": getattr(entity, "participants_count", None),
            "description": getattr(getattr(entity, "full_chat", None), "about", None),
        }


async def fetch_channel_posts(
    session: TelegramSession,
    username: str,
    limit: int = 20,
    min_id: int = 0,
) -> tuple[list[dict[str, Any]], int | None]:
    """
    Fetch posts from a Telegram channel.
    Returns (posts, max_message_id_seen).
    min_id: collect only messages with id > min_id (for incremental fetch).
    """
    try:
        from telethon.tl.types import MessageMediaDocument, MessageMediaPhoto, MessageReactions
    except ImportError as exc:
        raise TelegramClientError("telethon не установлен") from exc

    posts: list[dict[str, Any]] = []
    max_id_seen: int | None = None

    async with telegram_client(session) as client:
        entity = await client.get_entity(username)
        async for msg in client.iter_messages(entity, limit=limit, min_id=min_id):
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

            if max_id_seen is None or msg.id > max_id_seen:
                max_id_seen = msg.id

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

    return posts, max_id_seen
