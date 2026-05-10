"""
VK post → internal normalized format.
Handles: pinned posts, reposts, all attachment types, reactions, views, deleted posts.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def _unix_to_iso(ts: Any) -> str | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
    except (TypeError, ValueError):
        return None


def _unix_to_dt(ts: Any) -> datetime | None:
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _is_ad(raw: dict) -> bool:
    ma = raw.get("marked_as_ads")
    if isinstance(ma, dict):
        return bool(ma.get("marked_as_ads") or ma.get("is_marked"))
    if ma:
        return True
    return (raw.get("post_type") or "").lower() in ("post_ads", "ads", "suggest")


def _best_photo_url(photo: dict) -> str | None:
    sizes = photo.get("sizes") or []
    if not sizes:
        return photo.get("photo_2560") or photo.get("photo_807")
    best_url, best_area = None, -1
    for s in sizes:
        if not isinstance(s, dict):
            continue
        area = int(s.get("width") or 0) * int(s.get("height") or 0)
        if area >= best_area:
            best_area = area
            best_url = s.get("url")
    return best_url


def _parse_attachment(att: dict) -> dict[str, Any] | None:
    if not isinstance(att, dict):
        return None
    t = att.get("type")
    if not t:
        return None
    inner = att.get(t) or {}
    if not isinstance(inner, dict):
        inner = {}

    if t == "photo":
        url = _best_photo_url(inner)
        return (
            {
                "type": "photo",
                "url": url,
                "id": inner.get("id"),
                "owner_id": inner.get("owner_id"),
                "width": inner.get("width"),
                "height": inner.get("height"),
            }
            if url
            else None
        )

    if t == "video":
        oid, vid = inner.get("owner_id"), inner.get("id")
        page_url = f"https://vk.com/video{oid}_{vid}" if oid is not None and vid is not None else None
        url = inner.get("player") or page_url
        return {
            "type": "video",
            "url": url,
            "page_url": page_url if page_url != url else None,
            "title": inner.get("title"),
            "duration": inner.get("duration"),
            "views": inner.get("views"),
            "id": vid,
            "owner_id": oid,
        }

    if t == "audio":
        # Audio may be restricted by VK policy — return metadata only, no URL
        return {
            "type": "audio",
            "title": inner.get("title"),
            "artist": inner.get("artist"),
            "duration": inner.get("duration"),
            # url intentionally omitted (policy)
        }

    if t == "doc":
        return {
            "type": "doc",
            "url": inner.get("url"),
            "title": inner.get("title"),
            "ext": inner.get("ext"),
            "size": inner.get("size"),
        }

    if t == "link":
        lo = att.get("link") if isinstance(att.get("link"), dict) else inner
        if not isinstance(lo, dict):
            lo = inner
        return {"type": "link", "url": lo.get("url"), "title": lo.get("title")}

    if t == "poll":
        return {
            "type": "poll",
            "poll_id": inner.get("id"),
            "question": inner.get("question"),
            "votes": inner.get("votes"),
            "answers": [
                {"id": a.get("id"), "text": a.get("text"), "votes": a.get("votes")}
                for a in (inner.get("answers") or [])
                if isinstance(a, dict)
            ],
            "multiple": inner.get("multiple"),
            "anonymous": inner.get("anonymous"),
        }

    if t == "graffiti":
        return {"type": "graffiti", "url": inner.get("url")}

    if t == "page":
        url = inner.get("view_url")
        if not url and inner.get("group_id") and inner.get("id"):
            url = f"https://vk.com/page-{inner['group_id']}_{inner['id']}"
        return {"type": "page", "url": url, "title": inner.get("title")}

    if t == "sticker":
        imgs = inner.get("images") or []
        url = imgs[-1].get("url") if imgs else None
        return {"type": "sticker", "sticker_id": inner.get("sticker_id"), "url": url}

    # Unknown attachment — preserve type for future handling
    return {"type": str(t)}


def normalize_attachments(raw_list: list | None) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for att in raw_list or []:
        parsed = _parse_attachment(att)
        if parsed:
            # Strip None values for compactness
            out.append({k: v for k, v in parsed.items() if v is not None})
    return out


def normalize_reactions(raw: dict) -> dict[str, Any]:
    likes = raw.get("likes") or {}
    reposts = raw.get("reposts") or {}
    comments = raw.get("comments") or {}
    views = raw.get("views") or {}
    rx = raw.get("reactions")

    out: dict[str, Any] = {
        "likes_count": likes.get("count"),
        "reposts_count": reposts.get("count"),
        "comments_count": comments.get("count"),
        "views_count": views.get("count"),
    }
    if isinstance(rx, dict) and rx.get("items"):
        out["reaction_items"] = rx["items"]
    return {k: v for k, v in out.items() if v is not None}


def normalize_repost_info(raw: dict) -> dict[str, Any] | None:
    """Extract repost source info from copy_history."""
    history = raw.get("copy_history")
    if not isinstance(history, list) or not history:
        return None
    src = history[0]
    if not isinstance(src, dict):
        return None
    return {
        "original_post_id": src.get("id"),
        "original_owner_id": src.get("owner_id"),
        "original_text": src.get("text"),
        "original_date": _unix_to_iso(src.get("date")),
        "original_attachments": normalize_attachments(src.get("attachments")),
    }


def normalize_post(raw: dict) -> dict[str, Any] | None:
    """
    Normalize a single raw wall.get item to internal format.
    Returns None if post is deleted/unavailable.
    """
    post_id = raw.get("id")
    owner_id = raw.get("owner_id")
    if post_id is None or owner_id is None:
        return None

    # Deleted / unavailable posts
    if raw.get("deleted") or raw.get("is_deleted"):
        return {
            "vk_post_id": str(post_id),
            "owner_id": int(owner_id),
            "deleted": True,
            "published_at": _unix_to_iso(raw.get("date")),
        }

    repost = normalize_repost_info(raw)
    text = raw.get("text") or None
    # For pure reposts without own text, use original text as fallback
    if not text and repost:
        text = repost.get("original_text")

    result: dict[str, Any] = {
        "vk_post_id": str(post_id),
        "owner_id": int(owner_id),
        "from_id": raw.get("from_id"),
        "text": text,
        "published_at": _unix_to_iso(raw.get("date")),
        "published_dt": _unix_to_dt(raw.get("date")),
        "is_pinned": bool(raw.get("is_pinned")),
        "is_ad": _is_ad(raw),
        "post_type": raw.get("post_type"),
        "reactions": normalize_reactions(raw),
        "attachments": normalize_attachments(raw.get("attachments")),
    }
    if repost:
        result["repost"] = repost
    return result
