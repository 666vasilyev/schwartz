"""Кэш результатов аналитики: чтение последних значений, пересчёт (синхронно или в фоне), статус пересчёта."""
from __future__ import annotations

import asyncio
import hashlib
import math
import time
from datetime import datetime
from typing import Any

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.infrastructure.db.orm.models_vozd import (
    RunStatus,
    VozdAnalyticsCache,
    VozdBlacklistUser,
    VozdBlacklistWord,
    VozdRun,
)
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.db.project_scope import PROJECT_VOZD, use_project_scope
from app.use_case.vozd.analytics import service as svc
from app.use_case.vozd.analytics.catalog import CATALOG, SECTIONS, normalize_id, normalize_section
from app.use_case.vozd.analytics.context import Window, as_utc, utcnow
from app.use_case.vozd.analytics.registry import REGISTRY
from app.use_case.vozd.common import group_sources, iso
from app.utils.logger import get_logger

logger = get_logger(__name__)

_JOBS: dict[int, dict[str, Any]] = {}
_TASKS: set[asyncio.Task] = set()


# ── параметры ───────────────────────────────────────────────────────────────


def parse_sections(raw: str | None) -> list[str]:
    if not raw or not raw.strip():
        return list(SECTIONS)
    out: list[str] = []
    for part in raw.split(","):
        sec = normalize_section(part)
        if sec not in SECTIONS:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Неизвестный раздел «{part.strip()}»: допустимы 1, 2, 3, 4")
        if sec not in out:
            out.append(sec)
    return out


def parse_metrics(raw: str | None) -> list[str] | None:
    if not raw or not raw.strip():
        return None
    ids = [normalize_id(p) for p in raw.split(",") if p.strip()]
    unknown = [i for i in ids if i not in CATALOG]
    if unknown:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"Нет в каталоге: {', '.join(unknown)}")
    return list(dict.fromkeys(ids))


def window_key(window_days: int | None, date_from: datetime | None, date_to: datetime | None) -> str:
    if date_from or date_to:
        a = as_utc(date_from).date().isoformat() if date_from else ""
        b = as_utc(date_to).date().isoformat() if date_to else ""
        return f"{a}..{b}"
    return f"d{window_days}" if window_days else "all"


def clean_json(v: Any) -> Any:
    """Значения для JSON-колонки: NaN/inf → None (Postgres их не принимает)."""
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else v
    if isinstance(v, dict):
        return {str(k): clean_json(x) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [clean_json(x) for x in v]
    return v


# ── на каких данных считали (для пометки «устарело») ────────────────────────


async def current_inputs(db, group_id: int) -> dict[str, Any]:
    last_run = (
        await db.execute(
            select(func.max(VozdRun.id)).where(VozdRun.group_id == group_id, VozdRun.status == RunStatus.SUCCESS)
        )
    ).scalar_one()
    users = sorted(
        (await db.execute(select(VozdBlacklistUser.platform, VozdBlacklistUser.external_id).where(VozdBlacklistUser.group_id == group_id))).all()
    )
    words = sorted(
        (await db.execute(select(VozdBlacklistWord.lemma).where(VozdBlacklistWord.group_id == group_id))).scalars().all()
    )
    sig = hashlib.sha1(repr((users, words)).encode()).hexdigest()[:16]
    return {"run": int(last_run or 0), "blacklist": sig}


def _stale_reasons(row: VozdAnalyticsCache, cur: dict[str, Any]) -> list[str]:
    was = (row.meta or {}).get("inputs") or {}
    reasons = []
    if was.get("run") != cur["run"]:
        reasons.append("new_data")
    if was.get("blacklist") != cur["blacklist"]:
        reasons.append("blacklist_changed")
    return reasons


# ── чтение кэша ─────────────────────────────────────────────────────────────


def _item(spec, row, expert, cur, rows) -> dict[str, Any]:
    typ = svc.effective_status(spec)
    item: dict[str, Any] = {
        "id": spec.id,
        "title": spec.title,
        "type": typ,  # auto | llm | expert
        "duplicate_of": spec.duplicate_of,
    }
    if typ == "expert":
        item["status"] = "expert" if expert is not None else "expert_pending"
        hints = {}
        for h in spec.hints:
            hs = CATALOG.get(h)
            if hs is None or (hs.duplicate_of or hs.id) not in REGISTRY:
                continue
            hr = rows.get(h)
            hints[h] = (
                {"status": hr.status, "value": hr.value, "computed_at": iso(hr.computed_at)}
                if hr is not None
                else {"status": "not_computed"}
            )
        item["hints"] = hints
    elif row is None:
        item["status"] = "not_computed"
    else:
        item.update(
            status=row.status,
            quality=row.quality,
            value=row.value,
            reason=row.reason,
            computed_at=iso(row.computed_at),
            stale=bool(_stale_reasons(row, cur)),
            stale_reasons=_stale_reasons(row, cur),
        )
    if expert is not None:
        item["expert"] = svc._expert_dict(expert)  # noqa: SLF001
    return item


async def read_cached(
    db,
    group_id: int,
    sections: list[str],
    wkey: str,
    metric_ids: list[str] | None = None,
) -> dict[str, Any]:
    await svc._get_group(db, group_id)  # noqa: SLF001
    rows = {
        r.metric_id: r
        for r in (
            await db.execute(
                select(VozdAnalyticsCache).where(VozdAnalyticsCache.group_id == group_id, VozdAnalyticsCache.window_key == wkey)
            )
        ).scalars()
    }
    experts = await svc._expert_map(db, group_id)  # noqa: SLF001
    cur = await current_inputs(db, group_id)
    out_sections = []
    for sec in sections:
        items = []
        for spec in CATALOG.values():
            if spec.section != sec or (metric_ids is not None and spec.id not in metric_ids):
                continue
            items.append(_item(spec, rows.get(spec.id), experts.get(spec.id), cur, rows))
        counts: dict[str, int] = {}
        for it in items:
            counts[it["status"]] = counts.get(it["status"], 0) + 1
        times = [as_utc(rows[i["id"]].computed_at) for i in items if i["id"] in rows and i["type"] != "expert"]
        out_sections.append(
            {
                "id": sec,
                "title": SECTIONS[sec],
                "counts": counts,
                "computed_at": iso(max(times)) if times else None,
                "oldest_computed_at": iso(min(times)) if times else None,
                "stale": any(i.get("stale") for i in items),
                "metrics": items,
            }
        )
    return {
        "group_id": group_id,
        "window": wkey,
        "current_inputs": cur,
        "recalculation": job_state(group_id),
        "sections": out_sections,
    }


# ── пересчёт ────────────────────────────────────────────────────────────────


def job_state(group_id: int) -> dict[str, Any]:
    return dict(_JOBS.get(group_id) or {"state": "idle"})


def _begin(group_id: int, wkey: str, include_llm: bool) -> dict[str, Any]:
    cur = _JOBS.get(group_id)
    if cur and cur.get("state") == "running":
        raise HTTPException(status.HTTP_409_CONFLICT, "Расчёт аналитики для этой группы уже идёт")
    job = {
        "state": "running",
        "started_at": utcnow().isoformat(),
        "finished_at": None,
        "window": wkey,
        "include_llm": include_llm,
        "total": 0,
        "done": 0,
        "skipped_llm": [],
        "error": None,
    }
    _JOBS[group_id] = job
    return job


def _plan(sections: list[str], metric_ids: list[str] | None, include_llm: bool) -> tuple[list[str], list[str]]:
    """(что считать, какие LLM-метрики пропущены). Для экспертных пунктов добавляются их метрики-подсказки."""
    wanted = [m.id for m in CATALOG.values() if m.section in sections and (metric_ids is None or m.id in metric_ids)]
    compute: list[str] = []
    skipped: list[str] = []

    def add(mid: str) -> None:
        spec = CATALOG[mid]
        calc_id = spec.duplicate_of or spec.id
        if calc_id not in REGISTRY:
            return
        if REGISTRY[calc_id].llm and not include_llm:
            if mid not in skipped:
                skipped.append(mid)
            return
        if mid not in compute:
            compute.append(mid)

    for mid in wanted:
        spec = CATALOG[mid]
        if (spec.duplicate_of or spec.id) in REGISTRY:
            add(mid)
        else:
            for h in spec.hints:
                if h in CATALOG:
                    add(h)
    # оригиналы раньше дублей: дубль берёт готовый результат оригинала
    compute.sort(key=lambda m: 1 if CATALOG[m].duplicate_of else 0)
    return compute, skipped


async def _work(job: dict[str, Any], group_id: int, p: dict[str, Any]) -> None:
    t0 = time.monotonic()
    async with AsyncSessionLocal() as db:
        use_project_scope(db, PROJECT_VOZD)
        group = await svc._get_group(db, group_id)  # noqa: SLF001
        sources = await group_sources(db, group_id)
        window = Window.build(p["window_days"], p["date_from"], p["date_to"])
        ctx = await svc.build_context(
            db, group, sources, window,
            sample_size=p["sample_size"], sample_recent_days=p["sample_recent_days"],
            refresh=p["include_llm"], provider=p["provider"], model=p["model"],
        )
        inputs = await current_inputs(db, group_id)
        compute, skipped = _plan(p["sections"], p["metric_ids"], p["include_llm"])
        job["total"], job["skipped_llm"] = len(compute), skipped
        if any(m in ("1.1", "1.2") for m in compute):
            await svc.record_member_snapshots(db, group, sources, min_interval=None)
        results: dict[str, dict[str, Any]] = {}
        for mid in compute:
            spec = CATALOG[mid]
            calc_id = spec.duplicate_of or spec.id
            if spec.duplicate_of and spec.duplicate_of in results:
                results[mid] = results[spec.duplicate_of]
            else:
                results[mid] = await svc._run_calc(ctx, mid, calc_id)  # noqa: SLF001
            job["done"] += 1
        now = utcnow()
        async with AsyncSessionLocal() as wdb:
            for mid, res in results.items():
                row = {
                    "group_id": group_id,
                    "metric_id": mid,
                    "window_key": job["window"],
                    "status": res["status"],
                    "quality": res.get("quality"),
                    "value": clean_json(res.get("value")),
                    "reason": res.get("reason"),
                    "meta": {"inputs": inputs, "from_llm_cache": res.get("from_cache")},
                    "computed_at": now,
                }
                stmt = pg_insert(VozdAnalyticsCache).values(**row)
                await wdb.execute(
                    stmt.on_conflict_do_update(
                        constraint="uq_vozd_analytics_cache",
                        set_={k: row[k] for k in ("status", "quality", "value", "reason", "meta", "computed_at")},
                    )
                )
            await wdb.commit()
    job["summary"] = {
        "computed": sum(1 for r in results.values() if r["status"] == "computed"),
        "insufficient_data": sum(1 for r in results.values() if r["status"] == "insufficient_data"),
        "not_available": sum(1 for r in results.values() if r["status"] == "not_available"),
        "failed": sum(1 for r in results.values() if r["status"] == "failed"),
        "skipped_llm": len(skipped),
        "seconds": round(time.monotonic() - t0, 1),
    }


async def _run_job(job: dict[str, Any], group_id: int, p: dict[str, Any]) -> None:
    try:
        await _work(job, group_id, p)
        job["state"] = "done"
    except Exception as exc:  # noqa: BLE001
        job["state"] = "failed"
        job["error"] = f"{type(exc).__name__}: {str(getattr(exc, 'detail', exc))[:300]}"
        logger.error("vozd_analytics_recalc_failed", group_id=group_id, error=job["error"], exc_info=exc)
    finally:
        job["finished_at"] = utcnow().isoformat()


def _params(**kw: Any) -> dict[str, Any]:
    return kw


async def recalculate(group_id: int, *, wait: bool, **kw: Any) -> dict[str, Any]:
    """Запустить пересчёт: wait=True — дождаться и вернуть состояние, wait=False — запустить в фоне."""
    p = _params(**kw)
    wkey = window_key(p["window_days"], p["date_from"], p["date_to"])
    job = _begin(group_id, wkey, p["include_llm"])
    if wait:
        await _run_job(job, group_id, p)
        if job["state"] == "failed":
            raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Пересчёт не удался: {job['error']}")
    else:
        task = asyncio.create_task(_run_job(job, group_id, p))
        _TASKS.add(task)
        task.add_done_callback(_TASKS.discard)
    return dict(job)
