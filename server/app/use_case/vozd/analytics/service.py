"""Раздел «Аналитика»: каталог, расчёт списка метрик, экспертный ввод, сравнение периодов."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import delete, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import Source
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.db.orm.models_vozd import (
    SocialGroup,
    VozdAnalyticsExpert,
    VozdMemberSnapshot,
)
from app.use_case.vozd import blacklist as bl
from app.use_case.vozd.analytics import calc_general, calc_graph, calc_llm, calc_participants  # noqa: F401  (регистрация)
from app.use_case.vozd.analytics import util as u
from app.use_case.vozd.analytics.catalog import CATALOG, SECTIONS, MetricSpec
from app.use_case.vozd.analytics.context import AnalyticsContext, Window, as_utc, utcnow
from app.use_case.vozd.analytics.registry import REGISTRY, InsufficientData, MetricUnavailable
from app.use_case.vozd.common import group_sources, iso


def effective_status(spec: MetricSpec) -> str:
    target = CATALOG.get(spec.duplicate_of) if spec.duplicate_of else spec
    reg = REGISTRY.get(target.id) if target else None
    if reg is None:
        return "expert"
    return "llm" if reg.llm else "auto"


def catalog_item(spec: MetricSpec) -> dict[str, Any]:
    target = CATALOG.get(spec.duplicate_of) if spec.duplicate_of else None
    reg = REGISTRY.get((target or spec).id)
    return {
        "id": spec.id,
        "section": spec.section,
        "section_title": SECTIONS[spec.section],
        "title": spec.title,
        "status": effective_status(spec),  # auto | llm | expert
        "implemented": reg is not None,
        "planned_kind": spec.kind,
        "duplicate_of": spec.duplicate_of,
        "hint_metrics": [h for h in spec.hints if h in CATALOG],
        "note": reg.note if reg else None,
    }


def catalog(section: str | None = None) -> dict[str, Any]:
    items = [catalog_item(m) for m in CATALOG.values() if section is None or m.section == section]
    summary: dict[str, int] = {}
    for it in items:
        summary[it["status"]] = summary.get(it["status"], 0) + 1
    return {
        "sections": [{"id": k, "title": v} for k, v in SECTIONS.items()],
        "summary": summary,
        "items": items,
    }


# ── контекст ────────────────────────────────────────────────────────────────


async def _get_group(db: AsyncSession, group_id: int) -> SocialGroup:
    g = (
        await db.execute(select(SocialGroup).where(SocialGroup.id == group_id, SocialGroup.deleted_at.is_(None)))
    ).scalar_one_or_none()
    if g is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Социальная группа не найдена")
    return g


async def build_context(
    db: AsyncSession,
    group: SocialGroup,
    sources: list[Source],
    window: Window,
    *,
    flt: "bl.GroupFilter | None" = None,
    sample_size: int = 200,
    sample_recent_days: int = 7,
    refresh: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> AnalyticsContext:
    flt = flt or await bl.load_filter(db, group.id, sources)
    return AnalyticsContext(
        db, group, sources, flt, window,
        sample_size=sample_size, sample_recent_days=sample_recent_days,
        refresh=refresh, provider=provider, model=model,
    )


# ── расчёт ──────────────────────────────────────────────────────────────────


def _resolve(metric_id: str) -> tuple[MetricSpec | None, str | None]:
    spec = CATALOG.get(metric_id)
    if spec is None:
        return None, None
    return spec, (spec.duplicate_of or spec.id)


async def _expert_map(db: AsyncSession, group_id: int) -> dict[str, VozdAnalyticsExpert]:
    rows = (await db.execute(select(VozdAnalyticsExpert).where(VozdAnalyticsExpert.group_id == group_id))).scalars()
    return {r.metric_id: r for r in rows}


def _expert_dict(e: VozdAnalyticsExpert) -> dict[str, Any]:
    return {"value": e.value, "justification": e.justification, "expert": e.expert, "updated_at": iso(e.updated_at)}


async def _run_calc(ctx: AnalyticsContext, metric_id: str, calc_id: str) -> dict[str, Any]:
    """Расчёт одной метрики → {status, value|error, ...}. Ошибки метрики не роняют весь вызов."""
    reg = REGISTRY[calc_id]
    cache_key = f"result:{metric_id}"
    if cache_key in ctx._memo:  # noqa: SLF001 — повтор в одном запросе (подсказки)
        return ctx._memo[cache_key]  # noqa: SLF001
    ctx.metric_id = metric_id
    ctx.meta = {}
    try:
        value = await reg.fn(ctx)
        out = {
            "status": "computed",
            "quality": "llm_hypothesis" if reg.llm else "auto",
            "value": value,
            **ctx.meta,
        }
        if "computed_at" not in out:
            out["computed_at"] = utcnow().isoformat()
    except InsufficientData as exc:
        out = {"status": "insufficient_data", "reason": str(exc)}
    except MetricUnavailable as exc:
        out = {"status": "not_available", "reason": str(exc)}
    except HTTPException as exc:  # LLM недоступен и т.п.
        out = {"status": "failed", "reason": str(exc.detail)[:500]}
    except Exception as exc:  # noqa: BLE001
        out = {"status": "failed", "reason": f"{type(exc).__name__}: {exc}"[:500]}
        if isinstance(exc, SQLAlchemyError):
            await ctx.db.rollback()
    ctx._memo[cache_key] = out  # noqa: SLF001
    return out


async def compute_metrics(
    db: AsyncSession,
    group_id: int,
    metric_ids: list[str],
    *,
    window: Window,
    sample_size: int,
    sample_recent_days: int,
    refresh: bool,
    provider: str | None,
    model: str | None,
) -> dict[str, Any]:
    group = await _get_group(db, group_id)
    sources = await group_sources(db, group_id)
    ctx = await build_context(
        db, group, sources, window, sample_size=sample_size, sample_recent_days=sample_recent_days,
        refresh=refresh, provider=provider, model=model,
    )
    experts = await _expert_map(db, group_id)
    if any(m in ("I.1", "I.2") for m in metric_ids):
        await record_member_snapshots(db, group, sources, min_interval=timedelta(hours=1))
    results = []
    for mid in dict.fromkeys(metric_ids):  # без повторов, в порядке запроса
        spec, calc_id = _resolve(mid)
        if spec is None:
            results.append({"id": mid, "status": "unknown_metric", "reason": "нет в каталоге: GET /analytics/catalog"})
            continue
        item: dict[str, Any] = {"id": mid, "title": spec.title}
        if spec.duplicate_of:
            item["duplicate_of"] = spec.duplicate_of
        if calc_id in REGISTRY:
            item.update(await _run_calc(ctx, mid, calc_id))
        else:
            item["status"] = "expert" if mid in experts else "expert_pending"
            hints = {}
            for h in spec.hints:
                hspec = CATALOG.get(h)
                if hspec is None:
                    continue
                hid = hspec.duplicate_of or hspec.id
                reg = REGISTRY.get(hid)
                if reg is None:
                    continue
                if reg.llm:  # дорогие LLM-подсказки не считаем сами: только из кэша, если был расчёт
                    hints[h] = {"status": "llm_on_demand", "reason": "запросите метрику отдельно (LLM)"}
                    continue
                hints[h] = await _run_calc(ctx, h, hid)
            item["hints"] = hints
        if mid in experts:
            item["expert"] = _expert_dict(experts[mid])
        results.append(item)
    return {
        "group_id": group_id,
        "window": window.label(),
        "blacklist_applied": bool(ctx.flt.active),
        "results": results,
    }


# ── экспертный ввод ─────────────────────────────────────────────────────────


async def set_expert(db: AsyncSession, group_id: int, metric_id: str, value: Any, justification: str | None, expert: str | None) -> dict[str, Any]:
    await _get_group(db, group_id)
    if metric_id not in CATALOG:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Метрика {metric_id} не найдена в каталоге")
    now = utcnow()
    stmt = pg_insert(VozdAnalyticsExpert).values(
        group_id=group_id, metric_id=metric_id, value=value, justification=justification, expert=expert,
        created_at=now, updated_at=now,
    )
    await db.execute(
        stmt.on_conflict_do_update(
            constraint="uq_vozd_analytics_expert",
            set_={"value": value, "justification": justification, "expert": expert, "updated_at": now},
        )
    )
    await db.commit()
    e = (await _expert_map(db, group_id))[metric_id]
    return {"id": metric_id, "title": CATALOG[metric_id].title, "status": "expert", "expert": _expert_dict(e)}


async def delete_expert(db: AsyncSession, group_id: int, metric_id: str) -> dict[str, Any]:
    await _get_group(db, group_id)
    res = await db.execute(
        delete(VozdAnalyticsExpert).where(
            VozdAnalyticsExpert.group_id == group_id, VozdAnalyticsExpert.metric_id == metric_id
        )
    )
    await db.commit()
    return {"id": metric_id, "deleted": bool(res.rowcount)}


async def list_experts(db: AsyncSession, group_id: int) -> dict[str, Any]:
    await _get_group(db, group_id)
    em = await _expert_map(db, group_id)
    return {
        "items": [
            {"id": mid, "title": CATALOG[mid].title if mid in CATALOG else None, **_expert_dict(e)}
            for mid, e in sorted(em.items())
        ]
    }


# ── сравнение периодов ──────────────────────────────────────────────────────

_RANGE_RE = re.compile(r"^(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})$")


def parse_range(raw: str, name: str) -> Window:
    m = _RANGE_RE.match(raw.strip())
    if not m:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name}: ожидается YYYY-MM-DD..YYYY-MM-DD")
    try:
        d1 = datetime.fromisoformat(m.group(1)).replace(tzinfo=timezone.utc)
        d2 = datetime.fromisoformat(m.group(2)).replace(tzinfo=timezone.utc) + timedelta(days=1) - timedelta(seconds=1)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name}: {exc}") from exc
    if d2 < d1:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{name}: конец раньше начала")
    return Window(d1, d2)


async def compare(
    db: AsyncSession,
    group_id: int,
    metric_id: str,
    before: str,
    after: str,
    *,
    sample_size: int = 200,
    sample_recent_days: int = 7,
    refresh: bool = False,
    provider: str | None = None,
    model: str | None = None,
) -> dict[str, Any]:
    spec, calc_id = _resolve(metric_id)
    if spec is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Метрика {metric_id} не найдена в каталоге")
    if calc_id not in REGISTRY:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{metric_id}: метрика экспертная, сравнивать нечего")
    w_before, w_after = parse_range(before, "before"), parse_range(after, "after")
    group = await _get_group(db, group_id)
    sources = await group_sources(db, group_id)
    flt = await bl.load_filter(db, group_id, sources)
    out = {}
    for name, w in (("before", w_before), ("after", w_after)):
        ctx = await build_context(
            db, group, sources, w, flt=flt, sample_size=sample_size, sample_recent_days=sample_recent_days,
            refresh=refresh, provider=provider, model=model,
        )
        out[name] = {"window": w.label(), **await _run_calc(ctx, metric_id, calc_id)}
    diff = None
    if out["before"].get("status") == "computed" and out["after"].get("status") == "computed":
        diff = u.numeric_diff(out["before"]["value"], out["after"]["value"])
    return {"id": metric_id, "title": spec.title, "before": out["before"], "after": out["after"], "diff": diff}


# ── снимки численности (I.2) ────────────────────────────────────────────────


async def record_member_snapshots(
    db: AsyncSession, group: SocialGroup, sources: list[Source], *, min_interval: timedelta | None = None
) -> int:
    """Записать текущую численность источников (из source_metadata.members_count). Возвращает число записей.

    Пишет отдельной сессией, чтобы commit не «протухал» ORM-объекты вызывающей сессии."""
    gid = group.id
    rows = [(s.id, (s.source_metadata or {}).get("members_count")) for s in sources]
    async with AsyncSessionLocal() as wdb:
        if min_interval is not None:
            last = (
                await wdb.execute(
                    select(VozdMemberSnapshot.captured_at)
                    .where(VozdMemberSnapshot.group_id == gid)
                    .order_by(VozdMemberSnapshot.captured_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            if last is not None and utcnow() - as_utc(last) < min_interval:
                return 0
        n = 0
        for sid, cnt in rows:
            if isinstance(cnt, int) and cnt >= 0:
                wdb.add(VozdMemberSnapshot(group_id=gid, source_id=sid, members_count=cnt))
                n += 1
        if n:
            await wdb.commit()
        return n
