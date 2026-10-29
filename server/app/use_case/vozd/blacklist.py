"""Чёрные списки социальной группы (vozd): пользователи и слова.

Пользователь из ЧС и все его комментарии убираются из выдачи и статистики группы.
Слово из ЧС (с учётом словоформ: «акция» ≡ «акции», «акцию») скрывает пост или комментарий,
в тексте которого оно встречается; комментарии под скрытым постом тоже не выдаются и не учитываются.
Данные в базе не удаляются: запись из ЧС можно убрать, и всё вернётся.
"""
from __future__ import annotations

import asyncio
import re
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import sqlalchemy as sa
from fastapi import HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, PostComment, Source
from app.infrastructure.db.orm.models_vozd import (
    SocialGroup,
    VozdBlacklistUser,
    VozdBlacklistWord,
    VozdUser,
)

_TOKEN_RE = re.compile(r"[0-9a-zа-яё]+(?:[-'’][0-9a-zа-яё]+)*", re.I)
_CYR_RE = re.compile(r"[а-яё]", re.I)
_UID_RE = re.compile(r"^(vk|tg|telegram):(\d+)$")
_SCAN_BATCH = 5000
_CACHE_TTL = 60.0
_LEMMA_CACHE_MAX = 500_000

_lemma_cache: dict[str, str] = {}
# (group_id, подпись списка слов) -> (когда посчитано, id скрытых постов, id скрытых комментариев)
_hidden_cache: dict[tuple[int, tuple], tuple[float, list[int], list[int]]] = {}


# ── лемматизация ────────────────────────────────────────────────────────────


def tokenize(text: str | None) -> list[str]:
    return _TOKEN_RE.findall((text or "").lower().replace("ё", "е"))


def _ensure_lemmas_sync(tokens: Iterable[str]) -> None:
    if len(_lemma_cache) > _LEMMA_CACHE_MAX:
        _lemma_cache.clear()
    missing = {t for t in tokens if t not in _lemma_cache}
    cyr = []
    for t in missing:
        if _CYR_RE.search(t):
            cyr.append(t)
        else:
            _lemma_cache[t] = t
    if cyr:
        from app.application.services.content.lemmatizer.ru import lemmatize_ru_batch

        for t, lem in zip(cyr, lemmatize_ru_batch(cyr)):
            _lemma_cache[t] = lem.lower().replace("ё", "е")


async def ensure_lemmas(tokens: Iterable[str]) -> None:
    """Прогреть кэш лемм (spaCy — синхронный, поэтому в потоке, чтобы не блокировать event loop)."""
    tokens = list(tokens)
    if tokens:
        await asyncio.to_thread(_ensure_lemmas_sync, tokens)


async def normalize_entry(word: str) -> tuple[tuple[str, ...], tuple[str, ...]]:
    """(слова как введены, их начальные формы) для слова или короткой фразы."""
    toks = tokenize(word)
    if not toks:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Пустое слово: «{word}»")
    await ensure_lemmas(toks)
    return tuple(toks), tuple(_lemma_cache[t] for t in toks)


# ── фильтр группы ───────────────────────────────────────────────────────────


@dataclass
class WordMatcher:
    singles: set[str] = field(default_factory=set)  # леммы и исходные формы однословных записей
    phrases: list[tuple[str, ...]] = field(default_factory=list)  # леммы фраз из нескольких слов

    def matches_tokens(self, toks: list[str]) -> bool:
        lems = [_lemma_cache.get(t, t) for t in toks]
        if self.singles and (any(l in self.singles for l in lems) or any(t in self.singles for t in toks)):
            return True
        for ph in self.phrases:
            n = len(ph)
            if n <= len(lems) and any(tuple(lems[i : i + n]) == ph for i in range(len(lems) - n + 1)):
                return True
        return False


@dataclass
class GroupFilter:
    blocked: dict[str, set[int]] = field(default_factory=dict)  # platform -> external_id
    hidden_posts: list[int] = field(default_factory=list)
    hidden_comments: list[int] = field(default_factory=list)
    matcher: WordMatcher | None = None

    @property
    def active(self) -> bool:
        return bool(self.blocked or self.matcher)

    def is_blocked(self, platform: str, external_id: int) -> bool:
        return external_id in self.blocked.get(platform, ())

    async def hide_texts(self, texts: list[str | None]) -> list[bool]:
        """Какие из текстов содержат слова из ЧС (для постов со стен пользователей)."""
        if self.matcher is None:
            return [False] * len(texts)
        toks = [tokenize(t) for t in texts]
        await ensure_lemmas(t for ts in toks for t in ts)
        return [self.matcher.matches_tokens(ts) for ts in toks]


def _array(ids: list[int]):
    return sa.literal(ids, ARRAY(sa.BigInteger))


def post_visible(flt: GroupFilter | None):
    """Условие на Post: пост не скрыт словами из ЧС (None — условия нет)."""
    if flt is None or not flt.hidden_posts:
        return None
    return Post.id != sa.all_(_array(flt.hidden_posts))


def comment_visible(flt: GroupFilter | None, sources: list[Source]):
    """Условие на PostComment (запрос должен быть соединён с Post): комментарий не скрыт ЧС
    пользователей/слов и пост под ним не скрыт. None — условия нет."""
    if flt is None or not flt.active:
        return None
    conds = []
    if flt.hidden_comments:
        conds.append(PostComment.id != sa.all_(_array(flt.hidden_comments)))
    pv = post_visible(flt)
    if pv is not None:
        conds.append(pv)
    for platform, stype in (("vk", "vk"), ("telegram", "telegram")):
        ext = flt.blocked.get(platform)
        src_ids = [s.id for s in sources if s.source_type == stype]
        if ext and src_ids:
            conds.append(
                sa.not_(and_(Post.source_id.in_(src_ids), PostComment.from_id.in_(sorted(ext))))
            )
    return and_(*conds) if conds else None


def user_not_blocked(flt: GroupFilter | None):
    """Условие на VozdUser: пользователя нет в ЧС."""
    if flt is None or not flt.blocked:
        return None
    conds = [
        sa.not_(and_(VozdUser.platform == p, VozdUser.external_id.in_(sorted(ext))))
        for p, ext in flt.blocked.items()
        if ext
    ]
    return and_(*conds) if conds else None


# ── загрузка фильтра ────────────────────────────────────────────────────────


async def _scan_hidden(db: AsyncSession, sources: list[Source], matcher: WordMatcher) -> tuple[list[int], list[int]]:
    src_ids = [s.id for s in sources]
    posts: list[int] = []
    comments: list[int] = []
    if not src_ids:
        return posts, comments
    last = 0
    while True:
        rows = (
            await db.execute(
                select(Post.id, Post.text)
                .where(Post.source_id.in_(src_ids), Post.id > last)
                .order_by(Post.id)
                .limit(_SCAN_BATCH)
            )
        ).all()
        if not rows:
            break
        last = rows[-1][0]
        toks = [tokenize(t) for _i, t in rows]
        await ensure_lemmas(t for ts in toks for t in ts)
        posts += [pid for (pid, _t), ts in zip(rows, toks) if matcher.matches_tokens(ts)]
    last = 0
    while True:
        rows = (
            await db.execute(
                select(PostComment.id, PostComment.text)
                .join(Post, Post.id == PostComment.post_id)
                .where(Post.source_id.in_(src_ids), PostComment.id > last, PostComment.text.is_not(None))
                .order_by(PostComment.id)
                .limit(_SCAN_BATCH)
            )
        ).all()
        if not rows:
            break
        last = rows[-1][0]
        toks = [tokenize(t) for _i, t in rows]
        await ensure_lemmas(t for ts in toks for t in ts)
        comments += [cid for (cid, _t), ts in zip(rows, toks) if matcher.matches_tokens(ts)]
    return posts, comments


async def load_filter(db: AsyncSession, group_id: int, sources: list[Source]) -> GroupFilter:
    """Фильтр группы: пользователи в ЧС + id постов/комментариев со словами из ЧС."""
    flt = GroupFilter()
    for u in (await db.execute(select(VozdBlacklistUser).where(VozdBlacklistUser.group_id == group_id))).scalars():
        flt.blocked.setdefault(u.platform, set()).add(u.external_id)
    words = list(
        (await db.execute(select(VozdBlacklistWord).where(VozdBlacklistWord.group_id == group_id))).scalars()
    )
    if not words:
        return flt
    matcher = WordMatcher()
    for w in words:
        toks = tokenize(w.word)
        await ensure_lemmas(toks)
        lems = tuple(_lemma_cache[t] for t in toks)
        if len(lems) == 1:
            matcher.singles.update({lems[0], toks[0]})
        elif lems:
            matcher.phrases.append(lems)
    flt.matcher = matcher
    signature = (tuple(sorted(matcher.singles)), tuple(sorted(matcher.phrases)), tuple(sorted(s.id for s in sources)))
    key = (group_id, signature)
    cached = _hidden_cache.get(key)
    if cached is not None and time.monotonic() - cached[0] < _CACHE_TTL:
        flt.hidden_posts, flt.hidden_comments = cached[1], cached[2]
    else:
        flt.hidden_posts, flt.hidden_comments = await _scan_hidden(db, sources, matcher)
        for k in [k for k in _hidden_cache if k[0] == group_id]:
            _hidden_cache.pop(k, None)
        _hidden_cache[key] = (time.monotonic(), flt.hidden_posts, flt.hidden_comments)
    return flt


def invalidate(group_id: int) -> None:
    for k in [k for k in _hidden_cache if k[0] == group_id]:
        _hidden_cache.pop(k, None)


# ── управление списками ─────────────────────────────────────────────────────


def parse_uid(uid: str) -> tuple[str, int]:
    m = _UID_RE.match(uid.strip())
    if m is None:
        raise HTTPException(status_code=422, detail="uid: ожидается vk:<id> или tg:<id>")
    return ("vk" if m.group(1) == "vk" else "telegram"), int(m.group(2))


def _user_item(b: VozdBlacklistUser, user: VozdUser | None) -> dict[str, Any]:
    from app.use_case.vozd import common

    return {
        "id": b.id,
        "uid": common.user_uid(b.platform, b.external_id),
        "platform": b.platform,
        "external_id": b.external_id,
        "first_name": user.first_name if user else None,
        "last_name": user.last_name if user else None,
        "username": user.username if user else None,
        "note": b.note,
        "created_at": common.iso(b.created_at),
    }


async def list_users(db: AsyncSession, group_id: int) -> dict[str, Any]:
    rows = list(
        (
            await db.execute(
                select(VozdBlacklistUser).where(VozdBlacklistUser.group_id == group_id).order_by(VozdBlacklistUser.id)
            )
        ).scalars()
    )
    users: dict[tuple[str, int], VozdUser] = {}
    for platform in {r.platform for r in rows}:
        ids = [r.external_id for r in rows if r.platform == platform]
        for u in (
            await db.execute(select(VozdUser).where(VozdUser.platform == platform, VozdUser.external_id.in_(ids)))
        ).scalars():
            users[(platform, u.external_id)] = u
    items = [_user_item(r, users.get((r.platform, r.external_id))) for r in rows]
    return {"items": items, "total": len(items)}


async def add_user(db: AsyncSession, group_id: int, uid: str, note: str | None) -> dict[str, Any]:
    platform, ext = parse_uid(uid)
    exists = (
        await db.execute(
            select(VozdBlacklistUser.id).where(
                VozdBlacklistUser.group_id == group_id,
                VozdBlacklistUser.platform == platform,
                VozdBlacklistUser.external_id == ext,
            )
        )
    ).first()
    if exists is None:
        db.add(VozdBlacklistUser(group_id=group_id, platform=platform, external_id=ext, note=note))
        await db.commit()
    return await list_users(db, group_id)


async def remove_user(db: AsyncSession, group_id: int, uid: str) -> dict[str, Any]:
    platform, ext = parse_uid(uid)
    res = await db.execute(
        sa.delete(VozdBlacklistUser).where(
            VozdBlacklistUser.group_id == group_id,
            VozdBlacklistUser.platform == platform,
            VozdBlacklistUser.external_id == ext,
        )
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Пользователя нет в чёрном списке группы")
    await db.commit()
    return await list_users(db, group_id)


def _word_item(w: VozdBlacklistWord) -> dict[str, Any]:
    from app.use_case.vozd import common

    return {"id": w.id, "word": w.word, "lemma": w.lemma, "created_at": common.iso(w.created_at)}


async def list_words(db: AsyncSession, group_id: int) -> dict[str, Any]:
    rows = (
        await db.execute(
            select(VozdBlacklistWord).where(VozdBlacklistWord.group_id == group_id).order_by(VozdBlacklistWord.id)
        )
    ).scalars()
    items = [_word_item(w) for w in rows]
    return {"items": items, "total": len(items)}


async def add_words(db: AsyncSession, group_id: int, words: list[str]) -> dict[str, Any]:
    have = set(
        (await db.execute(select(VozdBlacklistWord.lemma).where(VozdBlacklistWord.group_id == group_id))).scalars()
    )
    for raw in words:
        raw = raw.strip()
        if not raw:
            continue
        _toks, lems = await normalize_entry(raw)
        lemma = " ".join(lems)
        if lemma in have:
            continue
        db.add(VozdBlacklistWord(group_id=group_id, word=raw[:255], lemma=lemma[:255]))
        have.add(lemma)
    await db.commit()
    invalidate(group_id)
    return await list_words(db, group_id)


async def remove_word(db: AsyncSession, group_id: int, word_id: int) -> dict[str, Any]:
    res = await db.execute(
        sa.delete(VozdBlacklistWord).where(VozdBlacklistWord.group_id == group_id, VozdBlacklistWord.id == word_id)
    )
    if res.rowcount == 0:
        raise HTTPException(status_code=404, detail="Слова нет в чёрном списке группы")
    await db.commit()
    invalidate(group_id)
    return await list_words(db, group_id)
