"""
Обогащение объектов wall.get: дата, реклама, вложения (URL), лайки/репосты/просмотры,
комментарии (wall.getComments).
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from app.infrastructure.vk import client as vk_client
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _unix_to_iso(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        sec = int(ts)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(sec, tz=timezone.utc).isoformat()


def _is_ad_post(raw: dict) -> bool:
    ma = raw.get("marked_as_ads")
    if isinstance(ma, dict):
        return bool(ma.get("marked_as_ads") or ma.get("is_marked"))
    if ma:
        return True
    pt = (raw.get("post_type") or "").lower()
    return pt in ("post_ads", "ads", "suggest")


def _best_photo_url(photo: dict) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return photo.get("photo_2560") or photo.get("photo_807")
    best_url = None
    best_area = -1
    for s in sizes:
        if not isinstance(s, dict):
            continue
        w = int(s.get("width") or 0)
        h = int(s.get("height") or 0)
        area = w * h
        if area >= best_area:
            best_area = area
            best_url = s.get("url")
    return best_url


def _parse_one_attachment(att: dict) -> dict[str, Any] | None:
    if not isinstance(att, dict):
        return None
    t = att.get("type")
    if not t:
        return None
    inner = att.get(t)
    if not isinstance(inner, dict):
        inner = {}

    if t == "photo":
        url = _best_photo_url(inner)
        if not url:
            return None
        return {"type": "photo", "url": url}

    if t == "video":
        oid = inner.get("owner_id")
        vid = inner.get("id")
        page_url = (
            f"https://vk.com/video{oid}_{vid}"
            if oid is not None and vid is not None
            else None
        )
        url = inner.get("player") or page_url
        out: dict[str, Any] = {"type": "video", "url": url}
        if page_url and page_url != url:
            out["page_url"] = page_url
        if inner.get("title"):
            out["title"] = inner["title"]
        if inner.get("duration") is not None:
            out["duration"] = inner["duration"]
        return out

    if t == "audio":
        out = {
            "type": "audio",
            "url": inner.get("url"),
            "title": inner.get("title"),
            "artist": inner.get("artist"),
        }
        return {k: v for k, v in out.items() if v is not None}

    if t == "doc":
        url = inner.get("url")
        if not url:
            return {"type": "doc", "title": inner.get("title")}
        out = {"type": "doc", "url": url}
        if inner.get("title"):
            out["title"] = inner["title"]
        if inner.get("ext"):
            out["ext"] = inner["ext"]
        return out

    if t == "link":
        lo = att.get("link") if isinstance(att.get("link"), dict) else inner
        if not isinstance(lo, dict):
            lo = inner
        out: dict[str, Any] = {"type": "link"}
        if lo.get("url"):
            out["url"] = lo["url"]
        if lo.get("title"):
            out["title"] = lo["title"]
        return out

    if t == "graffiti":
        url = inner.get("url")
        return {"type": "graffiti", "url": url} if url else {"type": "graffiti"}

    if t == "poll":
        return {
            "type": "poll",
            "poll_id": inner.get("id"),
            "question": inner.get("question"),
        }

    if t == "page":
        url = None
        if inner.get("view_url"):
            url = inner["view_url"]
        elif inner.get("group_id") is not None and inner.get("id"):
            url = f"https://vk.com/page-{inner['group_id']}_{inner['id']}"
        return {"type": "page", "url": url} if url else {"type": "page"}

    return {"type": str(t)}


def attachments_from_raw(raw_list: list[Any] | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for att in raw_list or []:
        if not isinstance(att, dict):
            continue
        parsed = _parse_one_attachment(att)
        if parsed:
            out.append(parsed)
    return out


def reactions_from_raw(raw: dict) -> dict[str, Any]:
    likes = raw.get("likes") if isinstance(raw.get("likes"), dict) else {}
    reposts = raw.get("reposts") if isinstance(raw.get("reposts"), dict) else {}
    views = raw.get("views") if isinstance(raw.get("views"), dict) else {}

    out: dict[str, Any] = {
        "likes_count": likes.get("count"),
        "user_likes": likes.get("user_likes"),
        "can_like": likes.get("can_like"),
        "reposts_count": reposts.get("count"),
        "views_count": views.get("count"),
    }
    rx = raw.get("reactions")
    if isinstance(rx, dict) and rx.get("items"):
        out["reaction_items"] = rx["items"]

    return {k: v for k, v in out.items() if v is not None}


def _normalise_comment(
    c: dict,
    *,
    depth: int = 0,
    max_depth: int = 2,
    max_replies: int = 10,
) -> dict[str, Any] | None:
    cid = c.get("id")
    if cid is None:
        return None
    from_id = c.get("from_id")
    rec: dict[str, Any] = {
        "id": int(cid),
        "from_id": int(from_id) if from_id is not None else None,
        "date": _unix_to_iso(c.get("date")),
        "text": (c.get("text") or None),
        "attachments": attachments_from_raw(c.get("attachments")),
    }

    thread = c.get("thread")
    if (
        depth < max_depth
        and isinstance(thread, dict)
        and isinstance(thread.get("items"), list)
    ):
        replies: list[dict[str, Any]] = []
        for r in thread["items"][:max_replies]:
            if not isinstance(r, dict):
                continue
            sub = _normalise_comment(
                r,
                depth=depth + 1,
                max_depth=max_depth,
                max_replies=max_replies,
            )
            if sub:
                replies.append(sub)
        if replies:
            rec["replies"] = replies
    return rec


async def fetch_comments_for_post(
    wall_owner_id: int,
    post_id: int,
    *,
    limit: int,
) -> list[dict[str, Any]]:
    if limit <= 0:
        return []
    try:
        data = await vk_client.wall_get_comments(
            wall_owner_id,
            post_id,
            count=limit,
            sort="desc",
            extended=1,
        )
    except Exception as exc:
        logger.warning(
            "vk_get_comments_failed",
            wall_owner_id=wall_owner_id,
            post_id=post_id,
            error=str(exc),
        )
        return []
    items = data.get("items") if isinstance(data, dict) else None
    if not isinstance(items, list):
        return []
    out: list[dict[str, Any]] = []
    for c in items:
        if not isinstance(c, dict):
            continue
        norm = _normalise_comment(c)
        if norm:
            out.append(norm)
    return out


def build_enriched_post_dict(
    raw: dict,
    *,
    comments: list[dict[str, Any]],
) -> dict[str, Any] | None:
    post_id = raw.get("id")
    owner_id = raw.get("owner_id")
    if post_id is None or owner_id is None:
        return None
    return {
        "vk_post_id": str(post_id),
        "owner_id": int(owner_id),
        "text": raw.get("text") or None,
        "published_at": _unix_to_iso(raw.get("date")),
        "is_ad": _is_ad_post(raw),
        "comments": comments,
        "reactions": reactions_from_raw(raw),
        "attachments": attachments_from_raw(raw.get("attachments")),
    }


async def enrich_wall_posts_with_comments(
    wall_owner_id: int,
    raw_posts: list[dict],
    *,
    comments_per_post: int,
    concurrency: int,
) -> list[dict[str, Any]]:
    if comments_per_post <= 0:
        return [
            r
            for r in (
                build_enriched_post_dict(x, comments=[]) for x in raw_posts
            )
            if r is not None
        ]
    sem = asyncio.Semaphore(max(1, concurrency))

    async def one(raw: dict) -> dict[str, Any] | None:
        post_id = raw.get("id")
        if post_id is None:
            return None
        async with sem:
            comments = await fetch_comments_for_post(
                wall_owner_id,
                int(post_id),
                limit=comments_per_post,
            )
        return build_enriched_post_dict(raw, comments=comments)

    results = await asyncio.gather(*[one(r) for r in raw_posts])
    return [r for r in results if r is not None]
