"""
Server-side VK wall collection: paginated, period-based, incremental.
Returns normalized posts; caller decides what to persist.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.infrastructure.vk.client import VkRateLimit, wall_get
from app.infrastructure.vk.normalizer import normalize_post
from app.utils.logger import get_logger

logger = get_logger(__name__)

_PAGE_SIZE = 100
_RATE_LIMIT_PAUSE = 2.0  # seconds to wait after rate-limit response


@dataclass
class WallCollectResult:
    posts: list[dict[str, Any]] = field(default_factory=list)
    fetched_count: int = 0
    pages_fetched: int = 0
    stopped_by: str = "limit"  # limit | period | post_id | exhausted


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _post_dt(post: dict) -> datetime | None:
    return post.get("published_dt")


async def _fetch_page(owner_id: int, offset: int) -> list[dict]:
    """Fetch one page; back off and retry once on rate-limit."""
    try:
        resp = await wall_get(owner_id, count=_PAGE_SIZE, offset=offset)
    except VkRateLimit:
        await asyncio.sleep(_RATE_LIMIT_PAUSE)
        resp = await wall_get(owner_id, count=_PAGE_SIZE, offset=offset)
    return resp.get("items") or []


async def collect_by_limit(
    owner_id: int,
    *,
    limit: int = 200,
    skip_pinned: bool = False,
    skip_ads: bool = False,
) -> WallCollectResult:
    """Collect up to `limit` most-recent posts."""
    result = WallCollectResult()
    offset = 0
    while result.fetched_count < limit:
        page = await _fetch_page(owner_id, offset)
        result.pages_fetched += 1
        if not page:
            result.stopped_by = "exhausted"
            break
        for raw in page:
            if not isinstance(raw, dict):
                continue
            post = normalize_post(raw)
            if post is None:
                continue
            if skip_pinned and post.get("is_pinned"):
                continue
            if skip_ads and post.get("is_ad"):
                continue
            result.posts.append(post)
            result.fetched_count += 1
            if result.fetched_count >= limit:
                result.stopped_by = "limit"
                return result
        offset += _PAGE_SIZE
        if len(page) < _PAGE_SIZE:
            result.stopped_by = "exhausted"
            break
    return result


async def collect_by_period(
    owner_id: int,
    *,
    date_from: datetime,
    date_to: datetime | None = None,
    max_posts: int = 5000,
    skip_ads: bool = False,
) -> WallCollectResult:
    """Collect posts in [date_from, date_to] range. Stops when post date < date_from."""
    if date_to is None:
        date_to = _utcnow()
    result = WallCollectResult()
    offset = 0
    while result.fetched_count < max_posts:
        page = await _fetch_page(owner_id, offset)
        result.pages_fetched += 1
        if not page:
            result.stopped_by = "exhausted"
            break
        for raw in page:
            if not isinstance(raw, dict):
                continue
            post = normalize_post(raw)
            if post is None:
                continue
            if skip_ads and post.get("is_ad"):
                continue
            dt = _post_dt(post)
            if dt is not None:
                if dt < date_from:
                    result.stopped_by = "period"
                    return result
                if dt > date_to:
                    continue
            result.posts.append(post)
            result.fetched_count += 1
            if result.fetched_count >= max_posts:
                result.stopped_by = "limit"
                return result
        offset += _PAGE_SIZE
        if len(page) < _PAGE_SIZE:
            result.stopped_by = "exhausted"
            break
    return result


async def collect_incremental(
    owner_id: int,
    *,
    since_post_id: str | int | None,
    max_posts: int = 1000,
    skip_ads: bool = False,
) -> WallCollectResult:
    """Collect posts newer than `since_post_id`. Stop when that ID is encountered."""
    since_id = int(since_post_id) if since_post_id is not None else None
    result = WallCollectResult()
    offset = 0
    while result.fetched_count < max_posts:
        page = await _fetch_page(owner_id, offset)
        result.pages_fetched += 1
        if not page:
            result.stopped_by = "exhausted"
            break
        for raw in page:
            if not isinstance(raw, dict):
                continue
            post = normalize_post(raw)
            if post is None:
                continue
            if skip_ads and post.get("is_ad"):
                continue
            raw_id = raw.get("id")
            if since_id is not None and raw_id is not None and int(raw_id) <= since_id:
                result.stopped_by = "post_id"
                return result
            result.posts.append(post)
            result.fetched_count += 1
            if result.fetched_count >= max_posts:
                result.stopped_by = "limit"
                return result
        offset += _PAGE_SIZE
        if len(page) < _PAGE_SIZE:
            result.stopped_by = "exhausted"
            break
    return result


def latest_post_id(result: WallCollectResult) -> str | None:
    """Return the VK post_id of the most recent (first) non-pinned post."""
    for post in result.posts:
        if not post.get("is_pinned"):
            return post.get("vk_post_id")
    return None
