"""Use-case'ы проекта vozd: социальные группы, источники, прогоны, выборки данных."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Post, Source, SourceStatus
from app.infrastructure.db.orm.models_vozd import (
    RunStage,
    RunStatus,
    SocialGroup,
    VozdRun,
    VozdUser,
    social_group_sources,
)
from app.infrastructure.db.project_scope import PROJECT_VOZD
from app.infrastructure.repositories.telegram_session import get_active_session
from app.infrastructure.telegram.client import resolve_channel
from app.infrastructure.vk.client import VKApiError
from app.presentation.schemas.vk import VkResolveRequest
from app.presentation.schemas.vozd import (
    VozdCollectRequest,
    VozdGroupCreate,
    VozdGroupUpdate,
    VozdSourceIn,
)
from app.use_case.vk.resolve import execute as vk_resolve
from app.use_case.vozd import common
from app.utils.logger import get_logger

logger = get_logger(__name__)

_TG_RE = re.compile(r"(?:https?://)?(?:t\.me|telegram\.me)/(?:s/)?([A-Za-z0-9_]{4,})", re.I)


def _now() -> datetime:
    return datetime.now(tz=timezone.utc)


def _422(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=detail)


# ── источники ───────────────────────────────────────────────────────────────


async def _get_or_create_source(db: AsyncSession, item: VozdSourceIn) -> Source:
    url = item.url.strip()
    if _TG_RE.search(url):
        return await _tg_source(db, url)
    if "vk.com" in url.lower() or "vk.ru" in url.lower() or re.fullmatch(r"[\w.]+", url):
        return await _vk_source(db, url)
    raise _422(f"Не удалось определить платформу по ссылке: {url}")


async def _vk_source(db: AsyncSession, url: str) -> Source:
    try:
        resolved = await vk_resolve(VkResolveRequest(url=url))
    except (ValueError, VKApiError) as exc:
        raise _422(f"VK: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=f"VK: {exc}") from exc
    owner_id = int(resolved.owner_id)
    existing = (
        await db.execute(
            select(Source).where(
                Source.source_type == "vk", Source.external_id == str(owner_id), Source.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    src = Source(
        project=PROJECT_VOZD,
        url=f"https://vk.com/{resolved.screen_name}",
        name=resolved.name,
        source_type="vk",
        username=resolved.screen_name,
        external_id=str(owner_id),
        vk_owner_id=owner_id,
        description=resolved.description,
        status=SourceStatus.ACTIVE.value,
        source_metadata={
            "members_count": resolved.members_count,
            "site": resolved.site,
            "verified": resolved.verified,
            "photo_url": resolved.photo_url,
            "name": resolved.name,
        },
    )
    db.add(src)
    await db.flush()
    return src


async def _tg_source(db: AsyncSession, url: str) -> Source:
    m = _TG_RE.search(url)
    assert m is not None
    username = m.group(1)
    existing = (
        await db.execute(
            select(Source).where(
                Source.source_type == "telegram", Source.username == username, Source.deleted_at.is_(None)
            )
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing
    info: dict[str, Any] = {}
    session = await get_active_session(db)
    if session is not None:
        try:
            info = await resolve_channel(session, username)
        except Exception as exc:  # noqa: BLE001
            logger.info("vozd_tg_resolve_failed", username=username, error=str(exc)[:200])
    src = Source(
        project=PROJECT_VOZD,
        url=f"https://t.me/{username}",
        name=info.get("title") or username,
        source_type="telegram",
        username=username,
        external_id=str(info["id"]) if info.get("id") else None,
        description=info.get("description"),
        status=SourceStatus.ACTIVE.value,
        source_metadata={"members_count": info.get("participants_count")},
    )
    db.add(src)
    await db.flush()
    return src


async def _link_sources(db: AsyncSession, group_id: int, items: list[VozdSourceIn]) -> None:
    linked = set(
        (
            await db.execute(
                select(social_group_sources.c.source_id).where(social_group_sources.c.group_id == group_id)
            )
        ).scalars()
    )
    for item in items:
        src = await _get_or_create_source(db, item)
        if src.id in linked:
            continue
        await db.execute(social_group_sources.insert().values(group_id=group_id, source_id=src.id))
        linked.add(src.id)


# ── группы ──────────────────────────────────────────────────────────────────


async def _get_group(db: AsyncSession, group_id: int) -> SocialGroup:
    g = await db.get(SocialGroup, group_id)
    if g is None or g.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Социальная группа не найдена")
    return g


def _params_dict(params) -> dict[str, Any] | None:
    if params is None:
        return None
    d = params.model_dump(exclude_none=True)
    return d or None


async def create_group(db: AsyncSession, body: VozdGroupCreate) -> dict[str, Any]:
    dup = (
        await db.execute(
            select(SocialGroup.id).where(SocialGroup.name == body.name, SocialGroup.deleted_at.is_(None))
        )
    ).first()
    if dup is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Группа с таким названием уже есть")
    group = SocialGroup(name=body.name, description=body.description, params=_params_dict(body.params))
    db.add(group)
    await db.flush()
    await _link_sources(db, group.id, body.sources)
    await db.commit()
    return await group_detail(db, group.id)


async def update_group(db: AsyncSession, group_id: int, body: VozdGroupUpdate) -> dict[str, Any]:
    g = await _get_group(db, group_id)
    if body.name is not None:
        g.name = body.name
    if body.description is not None:
        g.description = body.description
    if body.params is not None:
        merged = dict(g.params or {})
        merged.update(body.params.model_dump(exclude_none=True))
        g.params = merged or None
    await db.commit()
    return await group_detail(db, group_id)


async def delete_group(db: AsyncSession, group_id: int) -> None:
    g = await _get_group(db, group_id)
    g.deleted_at = _now()
    await db.commit()


async def add_sources(db: AsyncSession, group_id: int, items: list[VozdSourceIn]) -> dict[str, Any]:
    await _get_group(db, group_id)
    await _link_sources(db, group_id, items)
    await db.commit()
    return await group_detail(db, group_id)


async def remove_source(db: AsyncSession, group_id: int, source_id: int) -> dict[str, Any]:
    await _get_group(db, group_id)
    await db.execute(
        delete(social_group_sources).where(
            social_group_sources.c.group_id == group_id, social_group_sources.c.source_id == source_id
        )
    )
    await db.commit()
    return await group_detail(db, group_id)


def run_to_dict(r: VozdRun) -> dict[str, Any]:
    return {
        "id": r.id,
        "group_id": r.group_id,
        "status": r.status,
        "stage": r.stage,
        "params": r.params,
        "progress": r.progress,
        "error_message": r.error_message,
        "created_at": common.iso(r.created_at),
        "started_at": common.iso(r.started_at),
        "finished_at": common.iso(r.finished_at),
        "heartbeat_at": common.iso(r.heartbeat_at),
    }


async def _last_run(db: AsyncSession, group_id: int) -> VozdRun | None:
    return (
        await db.execute(
            select(VozdRun).where(VozdRun.group_id == group_id).order_by(VozdRun.id.desc()).limit(1)
        )
    ).scalar_one_or_none()


async def list_groups(db: AsyncSession) -> dict[str, Any]:
    groups = list(
        (
            await db.execute(
                select(SocialGroup).where(SocialGroup.deleted_at.is_(None)).order_by(SocialGroup.id)
            )
        ).scalars()
    )
    items = []
    for g in groups:
        sources = await common.group_sources(db, g.id)
        stats = await common.group_stats(db, sources)
        last = await _last_run(db, g.id)
        items.append(
            {
                "id": g.id,
                "name": g.name,
                "description": g.description,
                "stats": stats,
                "last_run": run_to_dict(last) if last else None,
            }
        )
    return {"items": items, "total": len(items)}


async def group_detail(db: AsyncSession, group_id: int) -> dict[str, Any]:
    g = await _get_group(db, group_id)
    sources = await common.group_sources(db, g.id)
    last = await _last_run(db, g.id)
    out = common.group_header(g, sources)
    out["stats"] = await common.group_stats(db, sources)
    out["last_run"] = run_to_dict(last) if last else None
    return out


async def group_data(
    db: AsyncSession,
    group_id: int,
    *,
    posts_skip: int,
    posts_limit: int,
    users_skip: int,
    users_limit: int,
    include_profiles: bool,
) -> dict[str, Any]:
    """Данные группы: посты с комментариями (универсальные ID) и участники с их активностью."""
    g = await _get_group(db, group_id)
    sources = await common.group_sources(db, g.id)
    src_by_id = {s.id: s for s in sources}
    out = common.group_header(g, sources)
    out["stats"] = await common.group_stats(db, sources)

    posts: list[Post] = []
    if src_by_id and posts_limit > 0:
        posts = list(
            (
                await db.execute(
                    select(Post)
                    .where(Post.source_id.in_(list(src_by_id)))
                    .order_by(Post.published_at.desc().nulls_last(), Post.id.desc())
                    .offset(posts_skip)
                    .limit(posts_limit)
                )
            ).scalars()
        )
    cmap = await common.comments_by_post(db, [p.id for p in posts])
    out["posts"] = [common.post_to_dict(src_by_id[p.source_id], p, cmap.get(p.id, [])) for p in posts]

    users: list[VozdUser] = []
    if users_limit > 0:
        ids_q = common.participants_query(sources).order_by(VozdUser.id).offset(users_skip).limit(users_limit)
        ids = list((await db.execute(ids_q)).scalars())
        if ids:
            users = list(
                (await db.execute(select(VozdUser).where(VozdUser.id.in_(ids)).order_by(VozdUser.id))).scalars()
            )
    details = await common.user_details(db, users, with_profile=include_profiles)
    activity = await common.user_activity(db, users, sources)
    for u, d in zip(users, details):
        d["activity"] = {"comments_count": len(activity[u.id]), "comments": activity[u.id]}
    out["users"] = details
    out["paging"] = {
        "posts": {"skip": posts_skip, "limit": posts_limit, "returned": len(posts), "total": out["stats"]["posts"]},
        "users": {"skip": users_skip, "limit": users_limit, "returned": len(users), "total": out["stats"]["participants"]},
    }
    return out


async def user_profile(
    db: AsyncSession, platform: str, external_id: int, group_id: int | None
) -> dict[str, Any]:
    """Профиль пользователя + где и что он писал (по всем группам или по одной)."""
    user = (
        await db.execute(
            select(VozdUser).where(VozdUser.platform == platform, VozdUser.external_id == external_id)
        )
    ).scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Пользователь не найден")
    sources = None
    if group_id is not None:
        await _get_group(db, group_id)
        sources = await common.group_sources(db, group_id)
    d = (await common.user_details(db, [user], with_profile=True))[0]
    act = (await common.user_activity(db, [user], sources))[user.id]
    d["activity"] = {"comments_count": len(act), "comments": act}
    return d


# ── прогоны ─────────────────────────────────────────────────────────────────


async def start_collect(db: AsyncSession, group_id: int, body: VozdCollectRequest) -> dict[str, Any]:
    await _get_group(db, group_id)
    sources = await common.group_sources(db, group_id)
    if not sources:
        raise _422("В группе нет источников")
    active = (
        await db.execute(
            select(VozdRun.id).where(
                VozdRun.group_id == group_id, VozdRun.status.in_([RunStatus.QUEUED, RunStatus.RUNNING])
            )
        )
    ).first()
    if active is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail=f"Для группы уже есть активный прогон #{active[0]}"
        )
    run = VozdRun(
        group_id=group_id,
        status=RunStatus.QUEUED,
        stage=RunStage.POSTS,
        params=body.model_dump(exclude_none=True) or None,
        progress={},
    )
    db.add(run)
    await db.commit()
    await db.refresh(run)
    return run_to_dict(run)


async def list_runs(db: AsyncSession, group_id: int, limit: int) -> dict[str, Any]:
    await _get_group(db, group_id)
    rows = (
        await db.execute(
            select(VozdRun).where(VozdRun.group_id == group_id).order_by(VozdRun.id.desc()).limit(limit)
        )
    ).scalars()
    items = [run_to_dict(r) for r in rows]
    return {"items": items, "total": len(items)}


async def get_run(db: AsyncSession, run_id: int) -> dict[str, Any]:
    r = await db.get(VozdRun, run_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Прогон не найден")
    return run_to_dict(r)


async def cancel_run(db: AsyncSession, run_id: int) -> dict[str, Any]:
    r = await db.get(VozdRun, run_id)
    if r is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Прогон не найден")
    if r.status in (RunStatus.QUEUED, RunStatus.RUNNING):
        r.status = RunStatus.CANCELLED
        r.finished_at = _now()
        await db.commit()
    return run_to_dict(r)

