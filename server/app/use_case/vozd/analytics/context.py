"""Контекст расчёта аналитики: окно, данные группы (с учётом чёрных списков), признаки текстов, кэш."""
from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, PostComment, Source
from app.infrastructure.db.orm.models_vozd import SocialGroup, VozdAnalyticsResult, VozdUser
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.use_case.vozd import blacklist as bl
from app.use_case.vozd.analytics import lexicons as lx

_WORD_RE = re.compile(r"[а-яёa-z]+", re.I)


def utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def as_utc(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


@dataclass(frozen=True)
class Window:
    date_from: datetime | None = None
    date_to: datetime | None = None

    @classmethod
    def build(cls, window_days: int | None, date_from: datetime | None, date_to: datetime | None) -> "Window":
        df, dt = as_utc(date_from), as_utc(date_to)
        if df is None and window_days:
            df = utcnow() - timedelta(days=window_days)
        return cls(df, dt)

    def label(self) -> dict[str, str | None]:
        return {
            "from": self.date_from.isoformat() if self.date_from else None,
            "to": self.date_to.isoformat() if self.date_to else None,
        }

    @property
    def days(self) -> float | None:
        if self.date_from is None:
            return None
        return max(((self.date_to or utcnow()) - self.date_from).total_seconds() / 86400, 0.0)


@dataclass
class Features:
    """Признаки одного текста (считаются один раз на весь расчёт)."""

    words: int = 0
    chars: int = 0
    lemmas: list[str] = field(default_factory=list)
    pos: int = 0
    neg: int = 0
    score: float = 0.0  # тональность -1..1 (лексикон + эмодзи)
    emotions: Counter = field(default_factory=Counter)
    aggression: int = 0
    compromise: int = 0
    profane: int = 0
    emojis: list[str] = field(default_factory=list)
    exclam: int = 0
    question: bool = False
    urls: list[str] = field(default_factory=list)
    hashtags: list[str] = field(default_factory=list)
    we: int = 0
    causal: int = 0
    cyr: int = 0
    lat: int = 0


@dataclass
class PostRow:
    id: int
    source_id: int
    platform: str
    published_at: datetime | None
    text: str
    likes: int
    reposts: int
    comments_count: int
    views: int
    attachments: list
    author_id: int | None
    url: str | None
    f: Features | None = None

    @property
    def engagement(self) -> int:
        return self.likes + self.reposts + self.comments_count


@dataclass
class CommentRow:
    id: int
    post_id: int
    source_id: int
    platform: str
    scid: int
    parent_id: int | None
    from_id: int | None
    text: str
    published_at: datetime | None
    attachments: list
    f: Features | None = None


def _num(v: Any) -> int:
    if isinstance(v, bool):
        return 0
    if isinstance(v, (int, float)):
        return int(v)
    return 0


def _likes(reactions: dict | None) -> tuple[int, int, int, int]:
    """(likes, reposts, comments, views) из reactions поста VK/Telegram."""
    r = reactions or {}
    inner = r.get("reactions")
    if isinstance(inner, dict):  # Telegram: {"reactions": {эмодзи: n}, "views_count", "comments_count"}
        likes = sum(_num(v) for v in inner.values())
        return likes, 0, _num(r.get("comments_count")), _num(r.get("views_count"))
    return _num(r.get("likes_count")), _num(r.get("reposts_count")), _num(r.get("comments_count")), _num(r.get("views_count"))


class AnalyticsContext:
    def __init__(
        self,
        db: AsyncSession,
        group: SocialGroup,
        sources: list[Source],
        flt: "bl.GroupFilter",
        window: Window,
        *,
        sample_size: int = 200,
        sample_recent_days: int = 7,
        refresh: bool = False,
        provider: str | None = None,
        model: str | None = None,
    ) -> None:
        self.db = db
        self.group = group
        self.sources = sources
        self.flt = flt
        self.window = window
        self.sample_size = sample_size
        self.sample_recent_days = sample_recent_days
        self.refresh = refresh
        self.provider = provider
        self.model = model
        self.metric_id = ""
        self.meta: dict[str, Any] = {}
        self._posts: list[PostRow] | None = None
        self._comments: list[CommentRow] | None = None
        self._users: dict[tuple[str, int], VozdUser] | None = None
        self._memo: dict[str, Any] = {}
        self._prepared = False

    # ── источники ───────────────────────────────────────────────────────────
    @property
    def source_ids(self) -> list[int]:
        return [s.id for s in self.sources]

    def platform_of(self, source_id: int) -> str:
        for s in self.sources:
            if s.id == source_id:
                return "telegram" if s.source_type == "telegram" else "vk"
        return "vk"

    def blocked(self, platform: str, external_id: int | None) -> bool:
        """Пользователь в чёрном списке группы (не участвует в метриках об участниках)."""
        return external_id is not None and self.flt is not None and self.flt.is_blocked(platform, external_id)

    # ── данные ──────────────────────────────────────────────────────────────
    async def posts(self) -> list[PostRow]:
        if self._posts is not None:
            return self._posts
        if not self.sources:
            self._posts = []
            return self._posts
        q = select(Post).where(Post.source_id.in_(self.source_ids))
        pv = bl.post_visible(self.flt)
        if pv is not None:
            q = q.where(pv)
        if self.window.date_from:
            q = q.where(Post.published_at >= self.window.date_from)
        if self.window.date_to:
            q = q.where(Post.published_at <= self.window.date_to)
        rows: list[PostRow] = []
        for p in (await self.db.execute(q.order_by(Post.published_at.asc().nulls_last(), Post.id))).scalars():
            likes, reposts, comments, views = _likes(p.reactions)
            payload = p.payload or {}
            author = payload.get("author_id")
            rows.append(
                PostRow(
                    id=p.id,
                    source_id=p.source_id or 0,
                    platform=self.platform_of(p.source_id or 0),
                    published_at=as_utc(p.published_at),
                    text=p.text or "",
                    likes=likes,
                    reposts=reposts,
                    comments_count=comments,
                    views=views,
                    attachments=p.attachments if isinstance(p.attachments, list) else [],
                    author_id=author if isinstance(author, int) else None,
                    url=payload.get("url"),
                )
            )
        self._posts = rows
        return rows

    async def comments(self) -> list[CommentRow]:
        if self._comments is not None:
            return self._comments
        if not self.sources:
            self._comments = []
            return self._comments
        q = (
            select(PostComment, Post.source_id)
            .join(Post, Post.id == PostComment.post_id)
            .where(Post.source_id.in_(self.source_ids))
        )
        cv = bl.comment_visible(self.flt, self.sources)
        if cv is not None:
            q = q.where(cv)
        if self.window.date_from:
            q = q.where(PostComment.published_at >= self.window.date_from)
        if self.window.date_to:
            q = q.where(PostComment.published_at <= self.window.date_to)
        rows: list[CommentRow] = []
        for c, source_id in (
            await self.db.execute(q.order_by(PostComment.published_at.asc().nulls_last(), PostComment.id))
        ).all():
            rows.append(
                CommentRow(
                    id=c.id,
                    post_id=c.post_id,
                    source_id=source_id or 0,
                    platform=self.platform_of(source_id or 0),
                    scid=c.source_comment_id,
                    parent_id=c.parent_id,
                    from_id=c.from_id,
                    text=c.text or "",
                    published_at=as_utc(c.published_at),
                    attachments=c.attachments if isinstance(c.attachments, list) else [],
                )
            )
        self._comments = rows
        return rows

    async def human_comments(self) -> list[CommentRow]:
        return [c for c in await self.comments() if c.from_id is not None and c.from_id > 0]

    async def users(self) -> dict[tuple[str, int], VozdUser]:
        """Профили участников (комментаторы и авторы постов окна), без пользователей из ЧС."""
        if self._users is not None:
            return self._users
        ids: dict[str, set[int]] = {"vk": set(), "telegram": set()}
        for c in await self.comments():
            if c.from_id and c.from_id > 0:
                ids[c.platform].add(c.from_id)
        for p in await self.posts():
            if p.author_id and p.author_id > 0 and not self.blocked(p.platform, p.author_id):
                ids[p.platform].add(p.author_id)
        out: dict[tuple[str, int], VozdUser] = {}
        for platform, ext in ids.items():
            ext_list = sorted(ext)
            for i in range(0, len(ext_list), 5000):
                part = ext_list[i : i + 5000]
                q = select(VozdUser).where(VozdUser.platform == platform, VozdUser.external_id.in_(part))
                for u in (await self.db.execute(q)).scalars():
                    out[(u.platform, u.external_id)] = u
        self._users = out
        return out

    def members_total(self) -> tuple[int, list[dict[str, Any]]]:
        total, items = 0, []
        for s in self.sources:
            n = (s.source_metadata or {}).get("members_count")
            items.append({"source_id": s.id, "name": s.name, "platform": s.source_type, "members_count": n})
            if isinstance(n, int):
                total += n
        return total, items

    # ── признаки текстов ────────────────────────────────────────────────────
    async def prepare(self) -> None:
        """Лемматизация всего корпуса одним проходом и расчёт признаков каждого текста."""
        if self._prepared:
            return
        posts, comments = await self.posts(), await self.comments()
        token_lists: dict[int, list[str]] = {}
        all_tokens: set[str] = set()
        rows: list[PostRow | CommentRow] = [*posts, *comments]
        for r in rows:
            toks = bl.tokenize(r.text)
            token_lists[id(r)] = toks
            all_tokens.update(toks)
        await bl.ensure_lemmas(all_tokens)
        cache = bl._lemma_cache
        for r in rows:
            toks = token_lists[id(r)]
            r.f = self._features(r.text, toks, [cache.get(t, t) for t in toks])
        self._prepared = True

    @staticmethod
    def _features(text: str, toks: list[str], lems: list[str]) -> Features:
        f = Features(words=len(toks), chars=len(text), lemmas=lems)
        for t, lem in zip(toks, lems):
            if t in lx.POSITIVE or lem in lx.POSITIVE:
                f.pos += 1
            if t in lx.NEGATIVE or lem in lx.NEGATIVE:
                f.neg += 1
            for emo, words in lx.EMOTIONS.items():
                if t in words or lem in words:
                    f.emotions[emo] += 1
            if t in lx.AGGRESSION or lem in lx.AGGRESSION:
                f.aggression += 1
            if t in lx.COMPROMISE or lem in lx.COMPROMISE:
                f.compromise += 1
            if lx.is_profane(t):
                f.profane += 1
            if t in lx.FIRST_PERSON_PLURAL:
                f.we += 1
        f.emojis = lx.EMOJI_RE.findall(text)
        for e in f.emojis:
            if e in lx.POSITIVE_EMOJI:
                f.pos += 1
            elif e in lx.NEGATIVE_EMOJI:
                f.neg += 1
        f.exclam = text.count("!")
        f.question = "?" in text
        f.urls = lx.URL_RE.findall(text)
        f.hashtags = [h.lower() for h in lx.HASHTAG_RE.findall(text)]
        low = text.lower()
        f.causal = sum(1 for m in lx.CAUSAL if m in low)
        letters = _WORD_RE.findall(text)
        for w in letters:
            if re.match(r"[а-яё]", w, re.I):
                f.cyr += len(w)
            else:
                f.lat += len(w)
        total = f.pos + f.neg
        f.score = round((f.pos - f.neg) / total, 4) if total else 0.0
        return f

    # ── служебное ───────────────────────────────────────────────────────────
    async def memo(self, key: str, factory: Callable[[], Awaitable[Any]]) -> Any:
        if key not in self._memo:
            self._memo[key] = await factory()
        return self._memo[key]

    def params_key(self, extra: str = "") -> str:
        raw = json.dumps(
            [
                self.window.label(),
                self.sample_size,
                self.sample_recent_days,
                self.provider,
                self.model,
                extra,
                sorted(self.flt.blocked.items()) if self.flt else None,
                len(self.flt.hidden_posts) if self.flt else 0,
                len(self.flt.hidden_comments) if self.flt else 0,
            ],
            default=lambda o: sorted(o) if isinstance(o, set) else str(o),
            sort_keys=True,
        )
        return hashlib.sha1(raw.encode()).hexdigest()

    async def cached(self, name: str, factory: Callable[[], Awaitable[Any]]) -> tuple[Any, datetime, bool]:
        """Результат дорогого (LLM) расчёта: из кэша БД или заново. Возвращает (значение, когда посчитано, из кэша)."""
        key = self.params_key()
        mem_key = f"cache:{name}:{key}"
        if mem_key in self._memo:
            v, at = self._memo[mem_key]
            return v, at, True
        if not self.refresh:
            row = (
                await self.db.execute(
                    select(VozdAnalyticsResult).where(
                        VozdAnalyticsResult.group_id == self.group.id,
                        VozdAnalyticsResult.metric_id == name,
                        VozdAnalyticsResult.params_key == key,
                    )
                )
            ).scalar_one_or_none()
            if row is not None:
                at = as_utc(row.computed_at) or utcnow()
                self._memo[mem_key] = (row.value, at)
                return row.value, at, True
        value = await factory()
        now = utcnow()
        # запись кэша — в отдельной сессии: commit основной сессии «протухает» загруженные ORM-объекты
        async with AsyncSessionLocal() as wdb:
            stmt = pg_insert(VozdAnalyticsResult).values(
                group_id=self.group.id, metric_id=name, params_key=key, value=value, computed_at=now
            )
            await wdb.execute(
                stmt.on_conflict_do_update(
                    constraint="uq_vozd_analytics_results", set_={"value": value, "computed_at": now}
                )
            )
            await wdb.commit()
        self._memo[mem_key] = (value, now)
        return value, now, False

    async def count_first_seen(self) -> dict[tuple[str, int], datetime]:
        """Когда пользователь впервые появился в наших данных (за всё время, без окна)."""
        if not self.sources:
            return {}

        async def load() -> dict[tuple[str, int], datetime]:
            q = (
                select(Post.source_id, PostComment.from_id, func.min(PostComment.published_at))
                .join(Post, Post.id == PostComment.post_id)
                .where(Post.source_id.in_(self.source_ids), PostComment.from_id > 0)
                .group_by(Post.source_id, PostComment.from_id)
            )
            cv = bl.comment_visible(self.flt, self.sources)
            if cv is not None:
                q = q.where(cv)
            out: dict[tuple[str, int], datetime] = {}
            for sid, uid, first in (await self.db.execute(q)).all():
                if first is None:
                    continue
                key = (self.platform_of(sid), uid)
                first = as_utc(first)
                if key not in out or first < out[key]:
                    out[key] = first
            return out

        return await self.memo("first_seen", load)
