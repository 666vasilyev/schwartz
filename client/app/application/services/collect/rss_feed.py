"""
Парсинг RSS/Atom: URL → нормализованные записи для JSON-ответа клиента.
"""
from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import feedparser

from app.infrastructure.rss.fetch import fetch_feed_bytes
from app.utils.html_text import strip_html
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MOCK: list[dict[str, Any]] = [
    {
        "rss_id": "mock-rss-1",
        "title": "MVP: запись из RSS (mock)",
        "link": "https://example.com/news/1",
        "published": None,
        "text": "Краткое описание mock-записи для теста.",
    },
    {
        "rss_id": "mock-rss-2",
        "title": "Вторая mock-запись",
        "link": "https://example.com/news/2",
        "published": None,
        "text": None,
    },
]


def normalize_feed_url(url: str) -> str:
    s = url.strip()
    if not s:
        raise ValueError("Пустой URL ленты")
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    p = urlparse(s)
    if not p.netloc:
        raise ValueError("В URL ленты нет хоста")
    return s


def _entry_text(entry: Any) -> str | None:
    # summary/content от feedparser часто содержат сырой HTML (<p>, <a>, списки) —
    # убираем разметку, оставляя читаемый текст (см. app/utils/html_text.py).
    if entry.get("summary"):
        return strip_html(str(entry.summary))
    if entry.get("content"):
        c = entry.content
        if isinstance(c, list) and c:
            v = c[0].get("value") if isinstance(c[0], dict) else getattr(c[0], "value", None)
            if v:
                return strip_html(str(v))
    return None


def _entry_id(entry: Any, idx: int) -> str:
    for key in ("id", "guid", "link"):
        v = entry.get(key)
        if v:
            if key == "guid" and isinstance(v, dict):
                gv = v.get("value")
                if gv:
                    return str(gv).strip()
            else:
                return str(v).strip()
    return f"rss-entry-{idx}"


def _entry_link(entry: Any) -> str | None:
    v = entry.get("link")
    return str(v).strip() if v else None


def _entry_title(entry: Any) -> str | None:
    t = entry.get("title")
    return str(t).strip() if t else None


def _entry_published(entry: Any) -> str | None:
    for key in ("published", "updated"):
        v = entry.get(key)
        if v:
            return str(v).strip()
    return None


def _parse_feed_bytes(body: bytes, *, limit: int) -> tuple[str | None, list[dict[str, Any]]]:
    parsed = feedparser.parse(body)
    if getattr(parsed, "bozo", False) and not parsed.entries:
        exc = getattr(parsed, "bozo_exception", None)
        hint = f": {exc}" if exc else ""
        raise ValueError(f"Не удалось разобрать ленту как RSS/Atom{hint}")

    title = None
    if parsed.feed and parsed.feed.get("title"):
        title = str(parsed.feed.title).strip() or None

    out: list[dict[str, Any]] = []
    for i, entry in enumerate(parsed.entries):
        if len(out) >= limit:
            break
        item = {
            "rss_id": _entry_id(entry, i),
            "title": _entry_title(entry),
            "link": _entry_link(entry),
            "published": _entry_published(entry),
            "text": _entry_text(entry),
        }
        out.append(item)

    return title, out


async def collect_rss_items_for_ingest(
    *,
    feed_url: str,
    limit: int = 20,
    use_mock: bool = False,
) -> tuple[str, str | None, list[dict[str, Any]]]:
    """
    Нормализованный URL ленты, заголовок фида (если есть), записи (не больше limit).
    """
    norm = normalize_feed_url(feed_url)

    if use_mock:
        logger.info("rss_using_mock", url=norm, limit=limit)
        return norm, "Mock RSS feed", list(_MOCK[:limit])

    body, _ctype = await fetch_feed_bytes(norm)
    if not body:
        raise ValueError("Пустой ответ при загрузке ленты")

    feed_title, items = _parse_feed_bytes(body, limit=limit)
    logger.info("rss_parsed", url=norm, n=len(items), feed_title=feed_title)
    return norm, feed_title, items
