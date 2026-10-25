"""Общие функции проекта vozd: универсальные ID, сериализация, выборка участников."""
from __future__ import annotations

from typing import Any

from sqlalchemy import Select, and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, PostComment, Source
from app.infrastructure.db.orm.models_vozd import (
    SocialGroup,
    VozdUser,
    VozdUserFriend,
    VozdUserGroup,
    VozdUserPost,
    social_group_sources,
)

PLATFORM_BY_SOURCE = {"vk": "vk", "telegram": "telegram"}
_UID_PREFIX = {"vk": "vk", "telegram": "tg"}


def _tg_name(src: Source) -> str:
    return (src.username or src.url or str(src.id)).lstrip("@").rsplit("/", 1)[-1]


def post_uid(src: Source, post: Post) -> str:
    if src.source_type == "vk":
        return f"vk:{post.owner_id}_{post.vk_post_id}"
    return f"tg:{_tg_name(src)}_{post.external_id}"


def comment_uid(src: Source, post: Post, source_comment_id: int) -> str:
    return f"{post_uid(src, post)}_{source_comment_id}"


def user_uid(platform: str, external_id: int) -> str:
    return f"{_UID_PREFIX.get(platform, platform)}:{external_id}"


def iso(dt: Any) -> str | None:
    return dt.isoformat() if dt is not None else None


def author_uid_for(platform: str, author_id: Any) -> str | None:
    """Универсальный ID автора: человек — `vk:123`, сообщество — `vk:community123`."""
    if not isinstance(author_id, int) or author_id == 0:
        return None
    prefix = _UID_PREFIX.get(platform, platform)
    return f"{prefix}:{author_id}" if author_id > 0 else f"{prefix}:community{abs(author_id)}"


def repost_text_only(repost: Any) -> Any:
    """Репост без вложений: проект собирает только текст и эмодзи."""
    if not isinstance(repost, dict):
        return repost
    return {k: v for k, v in repost.items() if k != "original_attachments"}


async def group_sources(db: AsyncSession, group_id: int) -> list[Source]:
    q = (
        select(Source)
        .join(social_group_sources, social_group_sources.c.source_id == Source.id)
        .where(social_group_sources.c.group_id == group_id, Source.deleted_at.is_(None))
        .order_by(Source.id)
    )
    return list((await db.execute(q)).scalars().all())


def source_to_dict(src: Source) -> dict[str, Any]:
    meta = src.source_metadata or {}
    return {
        "id": src.id,
        "platform": src.source_type,
        "url": src.url,
        "name": src.name,
        "screen_name": src.username,
        "external_id": src.external_id,
        "vk_owner_id": src.vk_owner_id,
        "description": src.description,
        "members_count": meta.get("members_count"),
        "site": meta.get("site"),
        "verified": meta.get("verified"),
    }


def comment_to_dict(src: Source, post: Post, c: PostComment, id_to_cid: dict[int, int]) -> dict[str, Any]:
    uid = comment_uid(src, post, c.source_comment_id)
    parent_uid = None
    if c.parent_id is not None and c.parent_id in id_to_cid:
        parent_uid = comment_uid(src, post, id_to_cid[c.parent_id])
    platform = PLATFORM_BY_SOURCE.get(src.source_type or "", src.source_type or "")
    author_uid = None
    if c.from_id is not None:
        author_uid = user_uid(platform, c.from_id) if c.from_id > 0 else f"{_UID_PREFIX.get(platform, platform)}:community{abs(c.from_id)}"
    return {
        "uid": uid,
        "comment_id": c.source_comment_id,
        "post_uid": post_uid(src, post),
        "parent_uid": parent_uid,
        "author_uid": author_uid,
        "author_id": c.from_id,
        "text": c.text,
        "published_at": iso(c.published_at),
    }


def post_to_dict(src: Source, post: Post, comments: list[PostComment] | None) -> dict[str, Any]:
    payload = post.payload or {}
    author_id = payload.get("author_id")
    platform = PLATFORM_BY_SOURCE.get(src.source_type or "", src.source_type or "")
    out: dict[str, Any] = {
        "uid": post_uid(src, post),
        "url": payload.get("url"),
        "platform": platform,
        "source_id": src.id,
        "source_name": src.name,
        "post_id": post.vk_post_id or post.external_id,
        "text": post.text,
        "published_at": iso(post.published_at),
        "author_uid": author_uid_for(platform, author_id),
        "author_id": author_id,
        "reactions": post.reactions,
        "repost": repost_text_only(payload.get("repost")),
        "comments_collected_at": iso(post.comments_collected_at),
    }
    if comments is not None:
        id_to_cid = {c.id: c.source_comment_id for c in comments}
        out["comments"] = [comment_to_dict(src, post, c, id_to_cid) for c in comments]
        out["comments_count"] = len(comments)
    return out


async def comments_by_post(db: AsyncSession, post_ids: list[int]) -> dict[int, list[PostComment]]:
    if not post_ids:
        return {}
    rows = (
        await db.execute(
            select(PostComment)
            .where(PostComment.post_id.in_(post_ids))
            .order_by(PostComment.post_id, PostComment.published_at.asc().nulls_last(), PostComment.id)
        )
    ).scalars().all()
    out: dict[int, list[PostComment]] = {}
    for r in rows:
        out.setdefault(r.post_id, []).append(r)
    return out


def participants_query(sources: list[Source]) -> Select:
    """Подзапрос id участников (комментаторы + авторы постов) для источников группы."""
    clauses = []
    for platform, stype in (("vk", "vk"), ("telegram", "telegram")):
        src_ids = [s.id for s in sources if s.source_type == stype]
        if not src_ids:
            continue
        commenters = (
            select(PostComment.from_id)
            .join(Post, Post.id == PostComment.post_id)
            .where(Post.source_id.in_(src_ids), PostComment.from_id > 0)
        )
        authors = select(Post.payload["author_id"].as_integer()).where(
            Post.source_id.in_(src_ids), Post.payload["author_id"].as_integer() > 0
        )
        clauses.append(
            and_(
                VozdUser.platform == platform,
                or_(VozdUser.external_id.in_(commenters), VozdUser.external_id.in_(authors)),
            )
        )
    if not clauses:
        return select(VozdUser.id).where(False)
    return select(VozdUser.id).where(or_(*clauses))


async def user_details(
    db: AsyncSession,
    users: list[VozdUser],
    *,
    with_profile: bool = True,
    parts: frozenset[str] | None = None,
) -> list[dict[str, Any]]:
    """Сериализация пользователей пачкой: профиль, группы, друзья, последние посты.

    `parts` ограничивает, что подгружать из {"groups", "friends", "posts"}; None — всё.
    """
    if not users:
        return []

    def want(part: str) -> bool:
        return parts is None or part in parts

    ids = [u.id for u in users]
    groups: dict[int, list[dict]] = {}
    friends: dict[int, list[int]] = {}
    wall: dict[int, list[dict]] = {}
    if with_profile:
        for g in (await db.execute(select(VozdUserGroup).where(VozdUserGroup.user_id.in_(ids if want("groups") else [])))).scalars():
            groups.setdefault(g.user_id, []).append(
                {"id": g.group_external_id, "name": g.name, "screen_name": g.screen_name, "url": g.url}
            )
        for f in (await db.execute(select(VozdUserFriend).where(VozdUserFriend.user_id.in_(ids if want("friends") else [])))).scalars():
            friends.setdefault(f.user_id, []).append(f.friend_external_id)
        for p in (
            await db.execute(
                select(VozdUserPost)
                .where(VozdUserPost.user_id.in_(ids if want("posts") else []))
                .order_by(VozdUserPost.published_at.desc().nulls_last())
            )
        ).scalars():
            wall.setdefault(p.user_id, []).append(
                {
                    "url": p.url,
                    "owner_id": p.owner_id,
                    "post_id": p.vk_post_id,
                    "text": p.text,
                    "published_at": iso(p.published_at),
                    "is_repost": p.is_repost,
                    "repost_of": repost_text_only(p.repost_of),
                    "reactions": p.reactions,
                }
            )
    out = []
    for u in users:
        d: dict[str, Any] = {
            "uid": user_uid(u.platform, u.external_id),
            "platform": u.platform,
            "external_id": u.external_id,
            "username": u.username,
            "first_name": u.first_name,
            "last_name": u.last_name,
            "profile_status": u.profile_status,
        }
        if with_profile:
            d.update(
                {
                    "about": u.about,
                    "profile": u.profile,
                    "profile_collected_at": iso(u.profile_collected_at),
                    "friends_status": u.friends_status,
                    "groups_status": u.groups_status,
                    "posts_status": u.posts_status,
                    "groups": groups.get(u.id, []),
                    "friends": sorted(friends.get(u.id, [])),
                    "posts": wall.get(u.id, []),
                }
            )
        out.append(d)
    return out


async def user_activity(
    db: AsyncSession, users: list[VozdUser], sources: list[Source] | None
) -> dict[int, list[dict[str, Any]]]:
    """Комментарии пользователей (где и что писали) с универсальными ID."""
    result: dict[int, list[dict[str, Any]]] = {u.id: [] for u in users}
    if not users:
        return result
    for platform in {u.platform for u in users}:
        by_ext = {u.external_id: u for u in users if u.platform == platform}
        stype = "vk" if platform == "vk" else "telegram"
        q = (
            select(PostComment, Post, Source)
            .join(Post, Post.id == PostComment.post_id)
            .join(Source, Source.id == Post.source_id)
            .where(Source.source_type == stype, PostComment.from_id.in_(list(by_ext)))
            .order_by(PostComment.published_at.asc().nulls_last(), PostComment.id)
        )
        if sources is not None:
            q = q.where(Source.id.in_([s.id for s in sources]))
        rows = (await db.execute(q)).all()
        parents: dict[int, int] = {}
        if rows:
            pids = [c.parent_id for c, _p, _s in rows if c.parent_id]
            if pids:
                for pc in (await db.execute(select(PostComment).where(PostComment.id.in_(pids)))).scalars():
                    parents[pc.id] = pc.source_comment_id
        for c, post, src in rows:
            user = by_ext[c.from_id]
            result[user.id].append(
                {
                    "uid": comment_uid(src, post, c.source_comment_id),
                    "post_uid": post_uid(src, post),
                    "post_url": (post.payload or {}).get("url"),
                    "source_id": src.id,
                    "source_name": src.name,
                    "parent_uid": comment_uid(src, post, parents[c.parent_id]) if c.parent_id in parents else None,
                    "text": c.text,
                    "published_at": iso(c.published_at),
                }
            )
    return result


async def group_stats(db: AsyncSession, sources: list[Source]) -> dict[str, int]:
    ids = [s.id for s in sources]
    if not ids:
        return {"sources": 0, "posts": 0, "comments": 0, "participants": 0, "profiles_collected": 0}
    posts = (await db.execute(select(func.count()).select_from(Post).where(Post.source_id.in_(ids)))).scalar_one()
    comments = (
        await db.execute(
            select(func.count())
            .select_from(PostComment)
            .join(Post, Post.id == PostComment.post_id)
            .where(Post.source_id.in_(ids))
        )
    ).scalar_one()
    pq = participants_query(sources).subquery()
    participants = (await db.execute(select(func.count()).select_from(pq))).scalar_one()
    collected = (
        await db.execute(
            select(func.count())
            .select_from(VozdUser)
            .where(VozdUser.id.in_(select(pq.c.id)), VozdUser.profile_collected_at.is_not(None))
        )
    ).scalar_one()
    return {
        "sources": len(ids),
        "posts": int(posts),
        "comments": int(comments),
        "participants": int(participants),
        "profiles_collected": int(collected),
    }


def group_header(group: SocialGroup, sources: list[Source]) -> dict[str, Any]:
    return {
        "id": group.id,
        "name": group.name,
        "description": group.description,
        "params": group.params,
        "composition": [source_to_dict(s) for s in sources],
        "created_at": iso(group.created_at),
    }

