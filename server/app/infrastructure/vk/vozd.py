"""
VK API для проекта vozd: полная пагинация комментариев (с ветками), профили,
друзья, группы и стена пользователя.

Использует общий пул токенов (`vk_call`), но без tenacity-ретраев на ошибках доступа
(закрытые профили — штатная ситуация) и с собственным ограничением частоты, которое
действует только на вызовы vozd и никак не влияет на сбор wall.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.config import get_settings
from app.infrastructure.vk.client import (
    VkAccessDenied,
    VkAuthError,
    VKApiError,
    VkNoAccessTokenConfigured,
    VkRateLimit,
    vk_call,
)
from app.infrastructure.vk.normalizer import normalize_attachments, normalize_post
from app.utils.logger import get_logger

logger = get_logger(__name__)

# vk_call обёрнут в tenacity (3 попытки на любую ошибку) — для vozd нужен «голый» вызов.
_raw_vk_call = getattr(vk_call, "__wrapped__", vk_call)

_pace_lock = asyncio.Lock()
_last_call_at = 0.0

USER_FIELDS = (
    "screen_name,sex,bdate,city,country,home_town,status,about,activities,interests,"
    "site,verified,followers_count,counters,occupation,photo_200,last_seen,"
    "is_closed,can_access_closed"
)

# Коды VK, означающие «данных нет / закрыто» (не сбой сбора)
_CLOSED_CODES = {7, 15, 19, 30, 203, 211, 212, 260}
_DELETED_CODES = {18}


async def _pace() -> None:
    global _last_call_at
    interval = get_settings().vozd_vk_min_interval_seconds
    async with _pace_lock:
        wait = interval - (time.monotonic() - _last_call_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_call_at = time.monotonic()


async def call(method: str, **params: Any) -> Any:
    """Вызов VK API: пейсинг, 2 ретрая на rate-limit/сетевые сбои, без ретраев на доступ."""
    last_exc: Exception | None = None
    for attempt in range(3):
        await _pace()
        try:
            return await _raw_vk_call(method, **params)
        except VkRateLimit as exc:
            last_exc = exc
            await asyncio.sleep(1.5 * (attempt + 1))
        except (httpx.HTTPError, asyncio.TimeoutError) as exc:
            last_exc = exc
            await asyncio.sleep(1.0 * (attempt + 1))
        except (VkAuthError, VkNoAccessTokenConfigured):
            raise
    assert last_exc is not None
    raise last_exc


def error_status(exc: Exception) -> str:
    """Статус данных по ошибке VK: closed | deleted | unavailable."""
    code = getattr(exc, "code", None)
    if code in _DELETED_CODES:
        return "deleted"
    if code in _CLOSED_CODES or isinstance(exc, VkAccessDenied):
        return "closed"
    return "unavailable"


# ── Посты стены ─────────────────────────────────────────────────────────────


def vozd_post(raw: dict) -> dict[str, Any] | None:
    """Нормализованный пост + автор (signer_id → from_id)."""
    post = normalize_post(raw)
    if post is None or post.get("deleted"):
        return None
    signer = raw.get("signer_id")
    from_id = raw.get("from_id")
    post["signer_id"] = signer
    post["author_id"] = signer if signer else from_id
    return post


async def iter_wall_posts(owner_id: int, limit: int) -> list[dict[str, Any]]:
    """До `limit` последних постов стены (wall.get постранично по 100)."""
    out: list[dict[str, Any]] = []
    offset = 0
    while len(out) < limit:
        resp = await call(
            "wall.get", owner_id=owner_id, count=min(100, limit - len(out)), offset=offset
        )
        items = (resp or {}).get("items") or []
        if not items:
            break
        for raw in items:
            if isinstance(raw, dict):
                p = vozd_post(raw)
                if p is not None:
                    out.append(p)
        offset += len(items)
        if len(items) < 1:
            break
        total = (resp or {}).get("count")
        if total is not None and offset >= int(total):
            break
    return out[:limit]


# ── Комментарии ─────────────────────────────────────────────────────────────


@dataclass
class CommentsResult:
    comments: list[dict[str, Any]] = field(default_factory=list)
    # id пользователя/сообщества → профиль из extended=1
    profiles: dict[int, dict[str, Any]] = field(default_factory=dict)
    status: str = "ok"  # ok | disabled


def _remember_profiles(resp: dict, profiles: dict[int, dict[str, Any]]) -> None:
    for p in resp.get("profiles") or []:
        if isinstance(p, dict) and p.get("id") is not None:
            profiles[int(p["id"])] = p
    for g in resp.get("groups") or []:
        if isinstance(g, dict) and g.get("id") is not None:
            profiles[-int(g["id"])] = g


def _comment_row(c: dict, *, thread_root: int | None) -> dict[str, Any] | None:
    cid = c.get("id")
    if cid is None:
        return None
    likes = c.get("likes") if isinstance(c.get("likes"), dict) else {}
    parent = c.get("reply_to_comment") or thread_root
    if parent == cid:
        parent = thread_root
    return {
        "id": int(cid),
        "parent_comment_id": int(parent) if parent else None,
        "thread_root_id": thread_root,
        "from_id": int(c["from_id"]) if c.get("from_id") is not None else None,
        "text": c.get("text") or None,
        "attachments": normalize_attachments(c.get("attachments")) or None,
        "date": c.get("date"),
        "likes_count": likes.get("count"),
        "deleted": bool(c.get("deleted")),
    }


async def fetch_all_comments(owner_id: int, post_id: int) -> CommentsResult:
    """Все комментарии поста с полными ветками (sort=asc: родитель раньше ответов)."""
    result = CommentsResult()
    seen: set[int] = set()
    offset = 0
    while True:
        try:
            resp = await call(
                "wall.getComments",
                owner_id=owner_id,
                post_id=post_id,
                count=100,
                offset=offset,
                sort="asc",
                extended=1,
                thread_items_count=10,
            )
        except VKApiError as exc:
            if exc.code in (212, 211, 15, 7, 19, 100, 18):  # комментарии закрыты/пост недоступен
                result.status = "disabled"
                return result
            raise
        resp = resp if isinstance(resp, dict) else {}
        _remember_profiles(resp, result.profiles)
        items = resp.get("items") or []
        for c in items:
            if not isinstance(c, dict):
                continue
            row = _comment_row(c, thread_root=None)
            if row is None or row["id"] in seen:
                continue
            seen.add(row["id"])
            result.comments.append(row)
            thread = c.get("thread") if isinstance(c.get("thread"), dict) else {}
            t_items = [t for t in (thread.get("items") or []) if isinstance(t, dict)]
            t_count = int(thread.get("count") or 0)
            if t_count > len(t_items):
                t_items = await _fetch_thread(owner_id, post_id, row["id"], result.profiles)
            for t in t_items:
                trow = _comment_row(t, thread_root=row["id"])
                if trow is None or trow["id"] in seen:
                    continue
                seen.add(trow["id"])
                result.comments.append(trow)
        offset += len(items)
        total = int(resp.get("count") or 0)
        if not items or offset >= total:
            break
    return result


async def _fetch_thread(
    owner_id: int, post_id: int, comment_id: int, profiles: dict[int, dict[str, Any]]
) -> list[dict]:
    out: list[dict] = []
    offset = 0
    while True:
        resp = await call(
            "wall.getComments",
            owner_id=owner_id,
            post_id=post_id,
            comment_id=comment_id,
            count=100,
            offset=offset,
            sort="asc",
            extended=1,
        )
        resp = resp if isinstance(resp, dict) else {}
        _remember_profiles(resp, profiles)
        items = [c for c in (resp.get("items") or []) if isinstance(c, dict)]
        out.extend(items)
        offset += len(items)
        if not items or offset >= int(resp.get("count") or 0):
            break
    return out


# ── Пользователи ────────────────────────────────────────────────────────────


async def users_get(user_ids: list[int]) -> list[dict[str, Any]]:
    """users.get пачкой (до 100 id)."""
    resp = await call("users.get", user_ids=",".join(str(i) for i in user_ids), fields=USER_FIELDS)
    return [u for u in (resp or []) if isinstance(u, dict)]


async def friends_get(user_id: int) -> list[int]:
    ids: list[int] = []
    offset = 0
    while True:
        resp = await call("friends.get", user_id=user_id, count=5000, offset=offset)
        items = (resp or {}).get("items") or []
        ids.extend(int(i) for i in items)
        offset += len(items)
        if not items or offset >= int((resp or {}).get("count") or 0):
            break
    return ids


async def groups_get(user_id: int) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    offset = 0
    while True:
        resp = await call(
            "groups.get",
            user_id=user_id,
            extended=1,
            fields="screen_name",
            count=1000,
            offset=offset,
        )
        items = [g for g in ((resp or {}).get("items") or []) if isinstance(g, dict)]
        out.extend(items)
        offset += len(items)
        if not items or offset >= int((resp or {}).get("count") or 0):
            break
    return out


async def user_wall(user_id: int, limit: int = 100) -> tuple[list[dict[str, Any]], int | None]:
    """Последние `limit` постов со стены пользователя, включая репосты, и общее число записей на стене."""
    out: list[dict[str, Any]] = []
    total: int | None = None
    offset = 0
    while len(out) < limit:
        resp = await call(
            "wall.get", owner_id=user_id, count=min(100, limit - len(out)), offset=offset
        )
        if (resp or {}).get("count") is not None:
            total = int(resp["count"])
        items = (resp or {}).get("items") or []
        if not items:
            break
        for raw in items:
            if not isinstance(raw, dict):
                continue
            p = vozd_post(raw)
            if p is not None:
                out.append(p)
        offset += len(items)
        if offset >= int((resp or {}).get("count") or 0):
            break
    return out[:limit], total
