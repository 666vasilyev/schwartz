"""Датасет социальной группы: комментаторы (по убыванию активности), их комментарии и профили."""
from __future__ import annotations

from collections import defaultdict
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
from app.use_case.vozd import blacklist as bl
from app.use_case.vozd import common

# Что можно подгрузить к профилю комментатора
USER_PARTS = ("groups", "friends", "posts")
# + публикации ресурсов группы (посты пабликов и каналов)
INCLUDE_PARTS = USER_PARTS + ("publications",)
_SEX = {1: "female", 2: "male"}


def parse_include(raw: str | None) -> frozenset[str]:
    """`groups,friends,posts,publications` через запятую; `all` — всё; пусто или `none` — ничего."""
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


def _resource(src: Source, stat: dict[str, int], posts: list[dict[str, Any]] | None) -> dict[str, Any]:
    d = common.source_to_dict(src)
    out: dict[str, Any] = {
        "id": d["id"],
        "platform": d["platform"],
        "url": d["url"],
        "name": d["name"],
        "screen_name": d["screen_name"],
        "description": d["description"],
        "members_count": d["members_count"],
        "stats": stat,
    }
    if posts is not None:
        out["posts"] = posts
    return out


async def _source_stats(
    db: AsyncSession, sources: list[Source], flt: "bl.GroupFilter | None" = None
) -> dict[int, dict[str, int]]:
    """Сверка по ресурсам: сколько комментариев заявляет платформа и сколько собрано (и чьи они)."""
    source_ids = [s.id for s in sources]
    stats = {
        sid: {
            "posts": 0,
            "comments_reported": 0,
            "comments_collected": 0,
            "comments_by_users": 0,
            "comments_by_communities": 0,
            "comments_no_author": 0,
        }
        for sid in source_ids
    }
    reported = func.coalesce(func.sum(func.coalesce(Post.reactions["comments_count"].as_integer(), 0)), 0)
    posts_q = select(Post.source_id, func.count(Post.id), reported).where(Post.source_id.in_(source_ids))
    pv = bl.post_visible(flt)
    if pv is not None:
        posts_q = posts_q.where(pv)
    for sid, n, rep in (await db.execute(posts_q.group_by(Post.source_id))).all():
        stats[sid]["posts"] = int(n)
        stats[sid]["comments_reported"] = int(rep)
    cnt = func.count(PostComment.id)
    comments_q = (
        select(
            Post.source_id,
            cnt,
            cnt.filter(PostComment.from_id > 0),
            cnt.filter(PostComment.from_id < 0),
            cnt.filter(PostComment.from_id.is_(None)),
        )
        .select_from(PostComment)
        .join(Post, Post.id == PostComment.post_id)
        .where(Post.source_id.in_(source_ids))
    )
    cv = bl.comment_visible(flt, sources)
    if cv is not None:
        comments_q = comments_q.where(cv)
    for sid, total, users, comm, noauth in (await db.execute(comments_q.group_by(Post.source_id))).all():
        stats[sid].update(
            comments_collected=int(total),
            comments_by_users=int(users),
            comments_by_communities=int(comm),
            comments_no_author=int(noauth),
        )
    return stats


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
    flt = await bl.load_filter(db, group.id, sources)
    group_stats = await common.group_stats(db, sources, flt)
    user_parts = frozenset(include) & frozenset(USER_PARTS)

    out: dict[str, Any] = {
        "group": group.name,
        "description": group.description,
        "generated_at": datetime.now(tz=timezone.utc).isoformat(),
        "resources": [],
        "stats": {
            "resources": group_stats["sources"],
            "posts": group_stats["posts"],
            "comments": group_stats["comments"],
            "comments_by_users": 0,
            "comments_by_communities": 0,
            "comments_no_author": 0,
        },
        "commenters": [],
        "paging": {"skip": skip, "limit": limit, "returned": 0, "total": 0, "min_comments": min_comments},
    }
    if not src_by_id:
        return out

    per_source = await _source_stats(db, sources, flt)
    for key in ("comments_by_users", "comments_by_communities", "comments_no_author"):
        out["stats"][key] = sum(s[key] for s in per_source.values())

    posts_by_source: dict[int, list[dict[str, Any]]] | None = None
    if "publications" in include:
        posts_by_source = defaultdict(list)
        pubs_q = select(Post).where(Post.source_id.in_(list(src_by_id)))
        pv = bl.post_visible(flt)
        if pv is not None:
            pubs_q = pubs_q.where(pv)
        for p in (
            await db.execute(
                pubs_q.order_by(Post.source_id, Post.published_at.desc().nulls_last(), Post.id.desc())
            )
        ).scalars():
            posts_by_source[p.source_id].append(common.post_to_dict(src_by_id[p.source_id], p, None))
    out["resources"] = [
        _resource(s, per_source[s.id], posts_by_source.get(s.id, []) if posts_by_source is not None else None)
        for s in sources
    ]

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
    cv = bl.comment_visible(flt, sources)
    if cv is not None:
        base = base.where(cv)
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

    activity = await common.user_activity(db, user_list, sources, flt) if user_list else {}
    details: dict[int, dict[str, Any]] = {}
    if user_parts and user_list:
        for u, d in zip(user_list, await common.user_details(db, user_list, with_profile=True, parts=user_parts, flt=flt)):
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
            p = u.profile or {}
            # Счётчики — по фактически собранному; статус показывает, был ли раздел доступен.
            info["friends_status"] = u.friends_status
            info["groups_status"] = u.groups_status
            info["wall_posts_status"] = u.posts_status
            info["friends_count"] = n_friends.get(u.id, 0) if u.friends_status == "ok" else None
            info["groups_count"] = n_groups.get(u.id, 0) if u.groups_status == "ok" else None
            info["wall_posts_count"] = n_wall.get(u.id, 0) if u.posts_status == "ok" else None
            info["wall_posts_total"] = p.get("wall_posts_total") if u.posts_status == "ok" else None
            d = details.get(u.id, {})
            if "groups" in user_parts:
                info["groups"] = d.get("groups", [])
            if "friends" in user_parts:
                info["friends"] = d.get("friends", [])
            if "posts" in user_parts:
                info["wall_posts"] = d.get("posts", [])
            comments = []
            for c in activity.get(u.id, []):
                src = src_by_id.get(c["source_id"])
                comments.append(
                    {
                        "uid": c["uid"],
                        "text": c["text"],
                        "attachments": c.get("attachments"),
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
