"""Telethon client factory — uses TelegramSession from DB."""
from __future__ import annotations

import json
import os
import time
from contextlib import asynccontextmanager
from typing import AsyncGenerator, Any
from urllib.parse import urlparse

from app.core.config import get_settings
from app.infrastructure.db.orm.models import TelegramSession


class TelegramClientError(Exception):
    pass


class NoActiveTelegramSession(TelegramClientError):
    pass


# ── FloodWait cooldown + кэш peer'ов ──────────────────────────────────────────
# ResolveUsernameRequest у Telegram жёстко лимитирован. Раньше каждый сбор делал
# get_entity(username) и при FloodWait планировщик ретраил каждые 1–5 минут,
# продлевая бан. Теперь: (1) resolve выполняется один раз на канал (кэш на диске),
# (2) при FloodWait в Telegram не ходим до конца ожидания.
_CACHE_PATH = os.environ.get("TG_ENTITY_CACHE_PATH", "/app/media/tg_entity_cache.json")
_entity_cache: dict[str, tuple[int, int]] | None = None
_flood_until: float = 0.0  # unix-time, до которого Telegram не трогаем


def _load_cache() -> dict[str, tuple[int, int]]:
    global _entity_cache
    if _entity_cache is None:
        try:
            with open(_CACHE_PATH, encoding="utf-8") as f:
                _entity_cache = {k: (int(v[0]), int(v[1])) for k, v in json.load(f).items()}
        except Exception:
            _entity_cache = {}
    return _entity_cache


def _save_cache() -> None:
    try:
        os.makedirs(os.path.dirname(_CACHE_PATH), exist_ok=True)
        with open(_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(_entity_cache or {}, f)
    except Exception:
        pass


def _check_cooldown() -> None:
    left = int(_flood_until - time.time())
    if left > 0:
        raise TelegramClientError(
            f"Telegram FloodWait: пауза ещё {left} с (запросы к Telegram приостановлены)"
        )


def _set_cooldown(seconds: int) -> None:
    global _flood_until
    _flood_until = max(_flood_until, time.time() + int(seconds) + 10)


async def _get_peer(client: Any, username: str) -> Any:
    """Возвращает peer канала; resolve по username только при промахе кэша."""
    from telethon.tl.types import Channel, InputPeerChannel

    key = username.lower().lstrip("@")
    cache = _load_cache()
    if key in cache:
        cid, ahash = cache[key]
        return InputPeerChannel(cid, ahash)

    entity = await client.get_entity(username)  # единственный ResolveUsername
    if isinstance(entity, Channel) and getattr(entity, "access_hash", None) is not None:
        cache[key] = (entity.id, entity.access_hash)
        _save_cache()
    return entity


def _build_proxy(proxy_url: str) -> tuple | None:
    """
    Convert proxy URL (e.g. socks5://user:pass@host:1080) to Telethon proxy tuple.
    Telethon format: (socks.SOCKS5, host, port[, True, username, password])
    """
    if not proxy_url:
        return None
    try:
        import socks  # PySocks
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
async def telegram_client(session: TelegramSession) -> AsyncGenerator[Any, None]:
    """
    Yields a connected Telethon TelegramClient routed through proxy.
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

    settings = get_settings()
    proxy = _build_proxy(settings.proxy)

    client = TelegramClient(
        StringSession(session.session_string),
        session.api_id,
        session.api_hash,
        proxy=proxy,
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

    try:
        from telethon.errors import FloodWaitError
    except ImportError as exc:
        raise TelegramClientError("telethon не установлен") from exc

    _check_cooldown()

    posts: list[dict[str, Any]] = []
    max_id_seen: int | None = None

    try:
        async with telegram_client(session) as client:
            entity = await _get_peer(client, username)
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
    except FloodWaitError as exc:
        _set_cooldown(exc.seconds)
        raise TelegramClientError(
            f"Telegram FloodWait: нужно подождать {exc.seconds} с"
        ) from exc
    except ValueError as exc:
        # устаревший peer в кэше (канал сменил username/удалён) — сбросить и пусть повторит
        _load_cache().pop(username.lower().lstrip("@"), None)
        _save_cache()
        raise TelegramClientError(f"Не удалось получить канал {username}: {exc}") from exc

    return posts, max_id_seen
