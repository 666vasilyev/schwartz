"""
Сбор данных проекта «воздействие» для социальной группы.

Стадии (каждая идемпотентна, чекпойнты — в БД, поэтому прогон можно продолжить):
  posts     — посты каждого источника группы (VK wall.get / Telegram канал);
  comments  — все комментарии с ветками + участники (vozd_users);
  profiles  — профили участников: описание, группы, друзья, последние посты/репосты.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.infrastructure.db.orm.models import Post, PostComment, Source
from app.infrastructure.db.orm.models_vozd import (
    RunStage,
    RunStatus,
    SocialGroup,
    VozdRun,
    VozdUser,
    VozdUserFriend,
    VozdUserGroup,
    VozdUserPost,
    social_group_sources,
)
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.db.project_scope import PROJECT_VOZD, use_project_scope
from app.infrastructure.repositories.telegram_session import get_active_session
from app.infrastructure.telegram.client import fetch_channel_posts
from app.infrastructure.telegram.vozd import fetch_comments_for_posts
from app.infrastructure.vk import vozd as vk
from app.infrastructure.vk.client import VKApiError, VkRateLimit
from app.utils.logger import get_logger

logger = get_logger(__name__)


class RunCancelled(Exception):
    pass


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _unix_dt(ts: Any) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(ts), tz=timezone.utc)
    except (TypeError, ValueError):
        return None


def _iso_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None


def group_params(group: SocialGroup, run: VozdRun) -> dict[str, Any]:
    s = get_settings()
    merged: dict[str, Any] = {
        "posts_per_source": s.vozd_posts_per_source_default,
        "comments_enabled": True,
        "comments_per_post_limit": None,
        "collect_profiles": True,
        "profile_posts_limit": s.vozd_profile_posts_limit,
    }
    merged.update({k: v for k, v in (group.params or {}).items() if v is not None})
    merged.update({k: v for k, v in (run.params or {}).items() if v is not None})
    merged["posts_per_source"] = max(1, min(int(merged["posts_per_source"]), s.vozd_posts_per_source_max))
    return merged


class Collector:
    def __init__(self, db: AsyncSession, run: VozdRun, group: SocialGroup, sources: list[Source]) -> None:
        self.db = db
        self.run = run
        self.group = group
        self.sources = sources
        self.params = group_params(group, run)
        self.progress: dict[str, Any] = dict(run.progress or {})
        self.progress.setdefault("done_sources", [])
        self.progress.setdefault("errors", [])

    # ── служебное ──────────────────────────────────────────────────────────

    async def checkpoint(self, **updates: Any) -> None:
        """Сохранить прогресс/heartbeat и проверить отмену."""
        self.progress.update(updates)
        self.run.progress = dict(self.progress)  # новый объект → SQLAlchemy видит изменение JSON
        self.run.heartbeat_at = _now()
        await self.db.commit()
        await self.db.refresh(self.run)
        if self.run.status == RunStatus.CANCELLED:
            raise RunCancelled()

    def note_error(self, message: str) -> None:
        errs = list(self.progress.get("errors") or [])
        errs.append(message[:300])
        self.progress["errors"] = errs[-20:]

    def source_ids(self) -> list[int]:
        return [s.id for s in self.sources]

    # ── main ───────────────────────────────────────────────────────────────

    async def run_all(self) -> None:
        order = [RunStage.POSTS, RunStage.COMMENTS, RunStage.PROFILES]
        start = order.index(self.run.stage) if self.run.stage in order else 0
        for stage in order[start:]:
            self.run.stage = stage
            await self.checkpoint(stage=stage)
            if stage == RunStage.POSTS:
                await self.stage_posts()
            elif stage == RunStage.COMMENTS:
                if self.params["comments_enabled"]:
                    await self.stage_comments()
            elif stage == RunStage.PROFILES:
                if self.params["collect_profiles"]:
                    await self.stage_profiles()
        self.run.stage = RunStage.DONE

    # ── стадия 1: посты ────────────────────────────────────────────────────

    async def stage_posts(self) -> None:
        limit = self.params["posts_per_source"]
        done = set(self.progress.get("done_sources") or [])
        for src in self.sources:
            if src.id in done:
                continue
            try:
                if src.source_type == "vk":
                    n = await self._posts_vk(src, limit)
                elif src.source_type == "telegram":
                    n = await self._posts_tg(src, limit)
                else:
                    self.note_error(f"source {src.id}: неподдерживаемый тип {src.source_type}")
                    n = 0
            except VKApiError as exc:
                if isinstance(exc, VkRateLimit):
                    raise
                self.note_error(f"source {src.id}: {exc}")
                n = 0
            done.add(src.id)
            counts = dict(self.progress.get("posts_by_source") or {})
            counts[str(src.id)] = n
            await self.checkpoint(done_sources=sorted(done), posts_by_source=counts)

    async def _posts_vk(self, src: Source, limit: int) -> int:
        if not src.vk_owner_id:
            raise ValueError(f"source {src.id}: не заполнен vk_owner_id")
        posts = await vk.iter_wall_posts(int(src.vk_owner_id), limit)
        for p in posts:
            await self._upsert_vk_post(src, p)
        await self.db.commit()
        return len(posts)

    async def _upsert_vk_post(self, src: Source, p: dict[str, Any]) -> Post:
        owner_id = int(p["owner_id"])
        vk_post_id = str(p["vk_post_id"])
        row = (
            await self.db.execute(
                select(Post).where(Post.owner_id == owner_id, Post.vk_post_id == vk_post_id)
            )
        ).scalar_one_or_none()
        payload = {
            "url": f"https://vk.com/wall{owner_id}_{vk_post_id}",
            "author_id": p.get("author_id"),
            "from_id": p.get("from_id"),
            "signer_id": p.get("signer_id"),
            "post_type": p.get("post_type"),
            "is_pinned": p.get("is_pinned"),
            "repost": p.get("repost"),
        }
        if row is None:
            row = Post(project=PROJECT_VOZD, source_id=src.id, vk_post_id=vk_post_id, owner_id=owner_id)
            self.db.add(row)
        row.source_id = src.id
        row.text = p.get("text")
        row.published_at = p.get("published_dt")
        row.is_ad = bool(p.get("is_ad"))
        row.reactions = p.get("reactions") or None
        row.payload = payload
        await self.db.flush()
        author = p.get("author_id")
        if isinstance(author, int) and author > 0:
            await self._ensure_users("vk", {author: {}})
        return row

    async def _posts_tg(self, src: Source, limit: int) -> int:
        tg_session = await get_active_session(self.db)
        if tg_session is None:
            raise RuntimeError("Нет активной Telegram-сессии")
        username = _tg_username(src)
        posts, _max_id = await asyncio.wait_for(
            fetch_channel_posts(tg_session, username, limit=limit, min_id=0),
            timeout=max(150, limit * 0.5),
        )
        for p in posts:
            ext = str(p["external_id"])
            row = (
                await self.db.execute(
                    select(Post).where(Post.source_id == src.id, Post.external_id == ext)
                )
            ).scalar_one_or_none()
            if row is None:
                row = Post(project=PROJECT_VOZD, source_id=src.id, external_id=ext)
                self.db.add(row)
            row.text = p.get("text")
            row.published_at = _iso_dt(p.get("published_at"))
            row.reactions = {"reactions": p.get("reactions") or {}, "views_count": p.get("views"),
                             "comments_count": p.get("comments")}
            row.payload = {
                "url": f"https://t.me/{username}/{ext}",
                "comments": p.get("comments", 0),
                "views": p.get("views", 0),
                "is_forwarded": p.get("is_forwarded", False),
            }
        await self.db.commit()
        return len(posts)

    # ── стадия 2: комментарии ──────────────────────────────────────────────

    async def stage_comments(self) -> None:
        total = (
            await self.db.execute(
                select(func.count()).select_from(Post).where(Post.source_id.in_(self.source_ids()))
            )
        ).scalar_one()
        await self.checkpoint(comments_posts_total=int(total))
        for src in self.sources:
            if src.source_type == "vk":
                await self._comments_vk(src)
            elif src.source_type == "telegram":
                await self._comments_tg(src)

    async def _pending_posts(self, src: Source) -> list[Post]:
        q = (
            select(Post)
            .where(Post.source_id == src.id, Post.comments_collected_at.is_(None))
            .order_by(Post.id)
        )
        return list((await self.db.execute(q)).scalars().all())

    async def _count_collected(self) -> int:
        q = (
            select(func.count())
            .select_from(Post)
            .where(Post.source_id.in_(self.source_ids()), Post.comments_collected_at.is_not(None))
        )
        return int((await self.db.execute(q)).scalar_one())

    async def _comments_vk(self, src: Source) -> None:
        pending = await self._pending_posts(src)
        for i, post in enumerate(pending, 1):
            expected = int((post.reactions or {}).get("comments_count") or 0)
            if expected > 0 and post.owner_id and post.vk_post_id:
                try:
                    res = await vk.fetch_all_comments(int(post.owner_id), int(post.vk_post_id))
                except VkRateLimit:
                    raise
                except VKApiError as exc:
                    self.note_error(f"post {post.id}: {exc}")
                    res = None
                if res is not None and res.comments:
                    entries = {
                        pid: {
                            "username": p.get("screen_name"),
                            "first_name": p.get("first_name"),
                            "last_name": p.get("last_name"),
                        }
                        for pid, p in res.profiles.items()
                        if pid > 0
                    }
                    await self._persist_comments(post, "vk", res.comments, entries)
            post.comments_collected_at = _now()
            await self.db.commit()
            if i % 10 == 0 or i == len(pending):
                await self.checkpoint(comments_posts_done=await self._count_collected())

    async def _comments_tg(self, src: Source) -> None:
        pending = [p for p in await self._pending_posts(src) if p.external_id]
        if not pending:
            return
        tg_session = await get_active_session(self.db)
        if tg_session is None:
            raise RuntimeError("Нет активной Telegram-сессии")
        username = _tg_username(src)
        chunk_size = 20
        for off in range(0, len(pending), chunk_size):
            chunk = pending[off : off + chunk_size]
            with_comments = [p for p in chunk if int((p.payload or {}).get("comments") or 0) > 0]
            fetched: dict[int, dict[str, Any]] = {}
            if with_comments:
                fetched = await _tg_fetch_with_flood_wait(
                    tg_session, username, [int(p.external_id) for p in with_comments],
                    limit=self.params.get("comments_per_post_limit"),
                )
            for post in chunk:
                data = fetched.get(int(post.external_id)) if post.external_id.isdigit() else None
                if data and data["comments"]:
                    entries = {sid: s for sid, s in data["senders"].items()}
                    await self._persist_comments(post, "telegram", data["comments"], entries)
                post.comments_collected_at = _now()
            await self.db.commit()
            await self.checkpoint(comments_posts_done=await self._count_collected())

    async def _persist_comments(
        self, post: Post, platform: str, comments: list[dict[str, Any]], user_entries: dict[int, dict]
    ) -> None:
        """Upsert комментариев поста: id строк сохраняются между прогонами."""
        author_entries = dict(user_entries)
        for c in comments:
            fid = c.get("from_id")
            if isinstance(fid, int) and fid > 0:
                author_entries.setdefault(fid, {})
        await self._ensure_users(platform, author_entries)

        existing = {
            r.source_comment_id: r
            for r in (
                await self.db.execute(select(PostComment).where(PostComment.post_id == post.id))
            ).scalars()
        }
        by_vk_id: dict[int, PostComment] = dict(existing)

        # порядок по глубине: родитель всегда сохранён (и имеет id) раньше потомка
        parent_of = {c["id"]: c.get("parent_comment_id") for c in comments}

        def depth(cid: int) -> int:
            d, cur, guard = 0, parent_of.get(cid), 0
            while cur and cur in parent_of and guard < 50:
                d, cur, guard = d + 1, parent_of.get(cur), guard + 1
            return d

        levels: dict[int, list[dict]] = {}
        for c in comments:
            levels.setdefault(depth(c["id"]), []).append(c)

        for lvl in sorted(levels):
            for c in levels[lvl]:
                row = by_vk_id.get(c["id"])
                if row is None:
                    row = PostComment(post_id=post.id, source_comment_id=c["id"])
                    self.db.add(row)
                    by_vk_id[c["id"]] = row
                parent_row = by_vk_id.get(c["parent_comment_id"]) if c.get("parent_comment_id") else None
                row.parent_id = parent_row.id if parent_row is not None and parent_row.id else None
                row.from_id = c.get("from_id")
                row.text = c.get("text")
                date = c.get("date")
                row.published_at = _unix_dt(date) if isinstance(date, (int, float)) else _iso_dt(date)
            await self.db.flush()

    async def _ensure_users(self, platform: str, entries: dict[int, dict[str, Any]]) -> None:
        ids = [i for i in entries if isinstance(i, int) and i > 0]
        if not ids:
            return
        rows = (
            await self.db.execute(
                select(VozdUser).where(VozdUser.platform == platform, VozdUser.external_id.in_(ids))
            )
        ).scalars().all()
        by = {r.external_id: r for r in rows}
        for i in ids:
            e = entries[i] or {}
            row = by.get(i)
            if row is None:
                row = VozdUser(
                    platform=platform,
                    external_id=i,
                    username=e.get("username"),
                    first_name=e.get("first_name"),
                    last_name=e.get("last_name"),
                    profile_status="pending",
                )
                if platform == "telegram":
                    # Из Telegram доступно только то, что видно в сообщениях.
                    row.about = e.get("about")
                    row.profile_status = "ok"
                    row.friends_status = row.groups_status = row.posts_status = "unsupported"
                    row.profile_collected_at = _now()
                self.db.add(row)
                by[i] = row
            else:
                row.username = row.username or e.get("username")
                row.first_name = row.first_name or e.get("first_name")
                row.last_name = row.last_name or e.get("last_name")
                if platform == "telegram" and not row.about and e.get("about"):
                    row.about = e["about"]
        await self.db.flush()

    # ── стадия 3: профили ──────────────────────────────────────────────────

    async def _participant_ids(self) -> list[int]:
        ids: set[int] = set()
        vk_sources = [s.id for s in self.sources if s.source_type == "vk"]
        if not vk_sources:
            return []
        q = (
            select(PostComment.from_id)
            .join(Post, Post.id == PostComment.post_id)
            .where(Post.source_id.in_(vk_sources), PostComment.from_id > 0)
            .distinct()
        )
        ids.update(int(i) for i in (await self.db.execute(q)).scalars().all() if i)
        authors = await self.db.execute(select(Post.payload).where(Post.source_id.in_(vk_sources)))
        for payload in authors.scalars():
            a = (payload or {}).get("author_id")
            if isinstance(a, int) and a > 0:
                ids.add(a)
        return sorted(ids)

    async def stage_profiles(self) -> None:
        ids = await self._participant_ids()
        await self.checkpoint(users_total=len(ids))
        limit_posts = int(self.params["profile_posts_limit"])
        done = 0
        for off in range(0, len(ids), 100):
            chunk = ids[off : off + 100]
            rows = (
                await self.db.execute(
                    select(VozdUser).where(
                        VozdUser.platform == "vk",
                        VozdUser.external_id.in_(chunk),
                        VozdUser.profile_collected_at.is_(None),
                    )
                )
            ).scalars().all()
            if not rows:
                done += len(chunk)
                continue
            try:
                infos = {int(u["id"]): u for u in await vk.users_get([r.external_id for r in rows])}
            except VKApiError as exc:
                if isinstance(exc, VkRateLimit):
                    raise
                self.note_error(f"users.get: {exc}")
                infos = {}
            for row in rows:
                await self._collect_profile(row, infos.get(row.external_id), limit_posts)
                await self.db.commit()
                done += 1
                if done % 10 == 0:
                    await self.checkpoint(profiles_done=done)
            await self.checkpoint(profiles_done=done)

    async def _collect_profile(self, row: VozdUser, info: dict[str, Any] | None, posts_limit: int) -> None:
        now = _now()
        if info is None:
            row.profile_status = "unavailable"
            row.friends_status = row.groups_status = row.posts_status = "unavailable"
            row.profile_collected_at = now
            return

        row.first_name = info.get("first_name") or row.first_name
        row.last_name = info.get("last_name") or row.last_name
        row.username = info.get("screen_name") or row.username
        about = " | ".join(x for x in (info.get("about"), info.get("status")) if x)
        row.about = about or None
        row.profile = {k: v for k, v in info.items() if k not in ("first_name", "last_name", "id")}

        deact = info.get("deactivated")
        if deact:
            status = "banned" if deact == "banned" else "deleted"
            row.profile_status = status
            row.friends_status = row.groups_status = row.posts_status = status
            row.profile_collected_at = now
            return
        if info.get("is_closed") and not info.get("can_access_closed"):
            row.profile_status = "closed"
            row.friends_status = row.groups_status = row.posts_status = "closed"
            row.profile_collected_at = now
            return
        row.profile_status = "ok"

        uid = row.id
        # друзья
        try:
            friends = await vk.friends_get(row.external_id)
            await self.db.execute(delete(VozdUserFriend).where(VozdUserFriend.user_id == uid))
            self.db.add_all([VozdUserFriend(user_id=uid, friend_external_id=f) for f in dict.fromkeys(friends)])
            row.friends_status = "ok"
        except VkRateLimit:
            raise
        except VKApiError as exc:
            row.friends_status = vk.error_status(exc)
        # группы
        try:
            groups = await vk.groups_get(row.external_id)
            await self.db.execute(delete(VozdUserGroup).where(VozdUserGroup.user_id == uid))
            seen: set[int] = set()
            for g in groups:
                gid = int(g.get("id"))
                if gid in seen:
                    continue
                seen.add(gid)
                sn = g.get("screen_name")
                self.db.add(
                    VozdUserGroup(
                        user_id=uid, group_external_id=gid, name=g.get("name"), screen_name=sn,
                        url=f"https://vk.com/{sn}" if sn else f"https://vk.com/club{gid}",
                    )
                )
            row.groups_status = "ok"
        except VkRateLimit:
            raise
        except VKApiError as exc:
            row.groups_status = vk.error_status(exc)
        # стена: последние посты и репосты
        try:
            posts = await vk.user_wall(row.external_id, posts_limit)
            await self.db.execute(delete(VozdUserPost).where(VozdUserPost.user_id == uid))
            seen_posts: set[tuple[int, str]] = set()
            for p in posts:
                key = (int(p["owner_id"]), str(p["vk_post_id"]))
                if key in seen_posts:
                    continue
                seen_posts.add(key)
                repost = p.get("repost")
                self.db.add(
                    VozdUserPost(
                        user_id=uid,
                        owner_id=key[0],
                        vk_post_id=key[1],
                        url=f"https://vk.com/wall{key[0]}_{key[1]}",
                        text=p.get("text"),
                        published_at=p.get("published_dt"),
                        is_repost=bool(repost),
                        repost_of=repost,
                        reactions=p.get("reactions") or None,
                    )
                )
            row.posts_status = "ok"
        except VkRateLimit:
            raise
        except VKApiError as exc:
            row.posts_status = vk.error_status(exc)
        row.profile_collected_at = now


def _tg_username(src: Source) -> str:
    import re

    if src.username:
        return src.username.lstrip("@")
    m = re.search(r"(?:t\.me|telegram\.me)/([A-Za-z0-9_]{4,})", src.url or "", re.I)
    return m.group(1) if m else (src.url or "").lstrip("@").strip()


async def _tg_fetch_with_flood_wait(session, username: str, ids: list[int], *, limit: int | None):
    try:
        from telethon.errors import FloodWaitError
    except ImportError:  # pragma: no cover
        FloodWaitError = ()  # type: ignore[assignment]
    for attempt in range(3):
        try:
            return await fetch_comments_for_posts(session, username, ids, per_post_limit=limit)
        except FloodWaitError as exc:  # type: ignore[misc]
            wait = min(int(getattr(exc, "seconds", 30)) + 1, 600)
            logger.warning("tg_vozd_flood_wait", seconds=wait)
            await asyncio.sleep(wait)
    raise RuntimeError("Telegram FloodWait: превышено число повторов")


# ── точка входа ─────────────────────────────────────────────────────────────


async def execute_run(run_id: int) -> None:
    """Выполнить прогон. Статус и ошибки пишутся в vozd_runs; исключения наружу не летят."""
    async with AsyncSessionLocal() as db:
        use_project_scope(db, PROJECT_VOZD)
        run = await db.get(VozdRun, run_id)
        if run is None:
            return
        group = await db.get(SocialGroup, run.group_id)
        if group is None or group.deleted_at is not None:
            run.status = RunStatus.FAILED
            run.error_message = "Социальная группа не найдена"
            run.finished_at = _now()
            await db.commit()
            return
        sources = list(
            (
                await db.execute(
                    select(Source)
                    .join(social_group_sources, social_group_sources.c.source_id == Source.id)
                    .where(social_group_sources.c.group_id == group.id, Source.deleted_at.is_(None))
                    .order_by(Source.id)
                )
            ).scalars()
        )
        collector = Collector(db, run, group, sources)
        try:
            if not sources:
                raise ValueError("В социальной группе нет источников")
            await collector.run_all()
            from app.use_case.vozd.dump import write_dump_file

            path = await write_dump_file(group.id)
            run.status = RunStatus.SUCCESS
            run.finished_at = _now()
            await collector.checkpoint(dump_path=path)
        except RunCancelled:
            logger.info("vozd_run_cancelled", run_id=run_id)
        except asyncio.CancelledError:
            # остановка приложения: вернуть в очередь, прогон продолжится с чекпойнта
            await db.rollback()
            run = await db.get(VozdRun, run_id)
            if run is not None and run.status == RunStatus.RUNNING:
                run.status = RunStatus.QUEUED
                await db.commit()
            raise
        except Exception as exc:  # noqa: BLE001
            logger.error("vozd_run_failed", run_id=run_id, error=str(exc)[:500], exc_info=exc)
            await db.rollback()
            run = await db.get(VozdRun, run_id)
            if run is not None:
                run.status = RunStatus.FAILED
                run.error_message = f"{type(exc).__name__}: {str(exc)[:500]}"
                run.finished_at = _now()
                await db.commit()
        else:
            await db.commit()
