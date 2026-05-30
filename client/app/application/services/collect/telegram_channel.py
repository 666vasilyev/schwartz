"""Telegram channel collector — thin service layer over infrastructure client."""
from __future__ import annotations

import re
from typing import Any

from app.core.config import get_settings
from app.infrastructure.telegram.client import TelegramClientError, collect_channel_posts

_TG_RE = re.compile(
    r"(?:https?://)?(?:t\.me|telegram\.me)/([A-Za-z0-9_]{5,})",
    re.IGNORECASE,
)


def _parse_username(url_or_username: str) -> str:
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
    Reads credentials from Settings (TELEGRAM_API_ID / TELEGRAM_API_HASH / TELEGRAM_SESSION_STRING).
    """
    settings = get_settings()
    if not settings.telegram_api_id or not settings.telegram_api_hash:
        raise ValueError(
            "Telegram API не настроен: укажите TELEGRAM_API_ID и TELEGRAM_API_HASH"
        )
    if not settings.telegram_session_string:
        raise ValueError(
            "Telegram сессия не настроена: укажите TELEGRAM_SESSION_STRING"
        )

    username = _parse_username(url)
    return await collect_channel_posts(
        api_id=settings.telegram_api_id,
        api_hash=settings.telegram_api_hash,
        session_string=settings.telegram_session_string,
        username=username,
        limit=limit,
    )
