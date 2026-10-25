"""Датасет социальной группы: комментаторы (по убыванию активности), их комментарии и профили."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, PostComment, Source
from app.infrastructure.db.orm.models_vozd import (
    SocialGroup,
    VozdUser,
    VozdUserFriend,
    VozdUserGroup,
    VozdUserPost,
)
from app.use_case.vozd import common

INCLUDE_PARTS = ("groups", "friends", "posts")
_SEX = {1: "female", 2: "male"}


def parse_include(raw: str | None) -> frozenset[str]:
    """`groups,friends,posts` через запятую; `all` — всё; пусто или `none` — ничего."""
    raw = (raw or "").strip().lower()
    if raw in ("", "none"):
        return frozenset()
    if raw == "all":
        return frozenset(INCLUDE_PARTS)
    parts = {x.strip() for x in raw.split(",") if x.strip()}
    bad = parts - set(INCLUDE_PARTS)
    if bad:
        raise HTTPException(
            status_code=422,
            detail=f"include: допустимо {', '.join(INCLUDE_PARTS)}, all, none; получено: {', '.join(sorted(bad))}",
        )
    return frozenset(parts)


async def get_group_by_name(db: AsyncSession, name: str) -> SocialGroup:
    """Поиск по названию: точное совпадение, иначе без учёта регистра."""
    wanted = name.strip()
    rows = (
        await db.execute(select(SocialGroup).where(SocialGroup.deleted_at.is_(None)))
    ).scalars().all()
    found = [g for g in rows if g.name == wanted] or [g for g in rows if g.name.casefold() == wanted.casefold()]
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Социальная группа «{wanted}» не найдена")
    if len(found) > 1:
        ids = ", ".join(str(g.id) for g in found)
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Название «{wanted}» подходит нескольким группам (id: {ids}); используйте /groups/{{id}}/dataset",
        )
    return found[0]


def _title(value: Any) -> str | None:
    return value.get("title") if isinstance(value, dict) else None


def _last_seen(value: Any) -> str | None:
    ts = value.get("time") if isinstance(value, dict) else None
    return datetime.fromtimestamp(ts, tz=timezone.utc).isoformat() if isinstance(ts, (int, float)) else None


def _user_url(u: VozdUser) -> str | None:
    if u.platform == "vk":
        return f"https://vk.com/{u.username}" if u.username else f"https://vk.com/id{u.external_id}"
    return f"https://t.me/{u.username}" if u.username else None


def _user_info(u: VozdUser) -> dict[str, Any]:
    p = u.profile or {}
    occ = p.get("occupation")
    return {
        "uid": common.user_uid(u.platform, u.external_id),
        "platform": u.platform,
        "external_id": u.external_id,
        "url": _user_url(u),
        "first_name": u.first_name,
        "last_name": u.last_name,
        "username": u.username,
        "profile_status": u.profile_status,
        "sex": _SEX.get(p.get("sex")),
        "birth_date": p.get("bdate"),
        "city": _title(p.get("city")),
        "country": _title(p.get("country")),
        "home_town": p.get("home_town"),
        "status": p.get("status"),
        "about": p.get("about"),
        "interests": p.get("interests"),
        "activities": p.get("activities"),
        "site": p.get("site"),
        "followers_count": p.get("followers_count"),
        "verified": bool(p.get("verified")) if "verified" in p else None,
        "occupation": {"type": occ.get("type"), "name": occ.get("name")} if isinstance(occ, dict) else None,
        "last_seen": _last_seen(p.get("last_seen")),
    }


async def _counts(db: AsyncSession, model: Any, user_ids: list[int]) -> dict[int, int]:
    if not user_ids:
        return {}
    rows = await db.execute(
        select(model.user_id, func.count()).where(model.user_id.in_(user_ids)).group_by(model.user_id)
    )
    return {uid: int(n) for uid, n in rows.all()}


def _resource(src: Source) -> dict[str, Any]:
    d = common.source_to_dict(src)
    return {
        "platform": d["platform"],
        "url": d["url"],
        "name": d["name"],
        "screen_name": d["screen_name"],
        "description": d["description"],
        "members_count": d["members_count"],
    }


async def build_dataset(
    db: AsyncSession,
    group: SocialGroup,
    *,
    min_comments: int,
    skip: int,
    limit: int | None,
    include: frozenset[str],
) -> dict[str, Any]:
    sources = await common.group_sources(db, group.id)
    src_by_id = {s.id: s for s in sources}
    stats = await common.group_stats(db, sources)

    out: dict[str, Any] = {
        "group": group.name,
        "description": group.description,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "resources": [_resource(s) for s in sources],
        "stats": {"resources": stats["sources"], "posts": stats["posts"], "comments": stats["comments"]},
        "commenters": [],
        "paging": {"skip": skip, "limit": limit, "returned": 0, "total": 0, "min_comments": min_comments},
    }
    if not src_by_id:
        return out

    cnt = func.count(PostComment.id)
    base = (
        select(
            Source.source_type.label("platform"),
            PostComment.from_id.label("ext"),
            cnt.label("n"),
        )
        .select_from(PostComment)
        .join(Post, Post.id == PostComment.post_id)
        .join(Source, Source.id == Post.source_id)
        .where(Source.id.in_(list(src_by_id)), PostComment.from_id > 0)
        .group_by(Source.source_type, PostComment.from_id)
        .having(cnt >= min_comments)
    )
    total = (await db.execute(select(func.count()).select_from(base.subquery()))).scalar_one()
    q = base.order_by(cnt.desc(), PostComment.from_id)
    if skip:
        q = q.offset(skip)
    if limit:
        q = q.limit(limit)
    rows = [(str(getattr(r.platform, "value", r.platform)), int(r.ext), int(r.n)) for r in (await db.execute(q)).all()]

    users: dict[tuple[str, int], VozdUser] = {}
    for platform in {r[0] for r in rows}:
        ids = [r[1] for r in rows if r[0] == platform]
        for u in (
            await db.execute(select(VozdUser).where(VozdUser.platform == platform, VozdUser.external_id.in_(ids)))
        ).scalars():
            users[(platform, u.external_id)] = u
    user_list = list(users.values())
    user_ids = [u.id for u in user_list]

    activity = await common.user_activity(db, user_list, sources) if user_list else {}
    details: dict[int, dict[str, Any]] = {}
    if include and user_list:
        for u, d in zip(user_list, await common.user_details(db, user_list, with_profile=True, parts=include)):
            details[u.id] = d
    n_friends = await _counts(db, VozdUserFriend, user_ids)
    n_groups = await _counts(db, VozdUserGroup, user_ids)
    n_wall = await _counts(db, VozdUserPost, user_ids)

    commenters: list[dict[str, Any]] = []
    for i, (platform, ext, n) in enumerate(rows, start=skip + 1):
        u = users.get((platform, ext))
        if u is None:
            info: dict[str, Any] = {
                "uid": common.user_uid(platform, ext),
                "platform": platform,
                "external_id": ext,
                "profile_status": "not_collected",
            }
            comments: list[dict[str, Any]] = []
        else:
            info = _user_info(u)
            collected = u.profile_status == "ok"
            info["friends_count"] = n_friends.get(u.id, 0) if collected else None
            info["groups_count"] = n_groups.get(u.id, 0) if collected else None
            info["wall_posts_count"] = n_wall.get(u.id, 0) if collected else None
            d = details.get(u.id, {})
            if "groups" in include:
                info["groups"] = d.get("groups", [])
            if "friends" in include:
                info["friends"] = d.get("friends", [])
            if "posts" in include:
                info["wall_posts"] = d.get("posts", [])
            comments = []
            for c in activity.get(u.id, []):
                src = src_by_id.get(c["source_id"])
                comments.append(
                    {
                        "uid": c["uid"],
                        "text": c["text"],
                        "published_at": c["published_at"],
                        "public": {
                            "id": c["source_id"],
                            "name": c["source_name"],
                            "url": src.url if src else None,
                            "screen_name": src.username if src else None,
                        },
                        "post_uid": c["post_uid"],
                        "post_url": c["post_url"],
                        "parent_uid": c["parent_uid"],
                    }
                )
        commenters.append({"rank": i, "comments_count": n, "user": info, "comments": comments})

    out["commenters"] = commenters
    out["paging"].update({"returned": len(commenters), "total": int(total)})
    return out
