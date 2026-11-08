"""
Раздел «Аналитика» проекта «воздействие» — /api/v1/vozd/…

Номера разделов арабские: 1 — общие сведения о группе, 2 — участники, 3 — цифровой контент и динамика,
4 — психологическое воздействие (экспертный ввод). Метрика адресуется id вида «2.28».

Схема работы фронта:
  1. GET  /groups/{id}/analytics                — последние рассчитанные значения (с датой расчёта);
  2. GET  /groups/{id}/analytics/recalculate    — пересчитать (сразу или в фоне) и сохранить в кэш;
  3. GET  /groups/{id}/analytics/status         — ход фонового пересчёта.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_current_user
from app.presentation.api.routes.vozd import get_vozd_session
from app.presentation.schemas.vozd import VozdAnalyticsExpertInput
from app.use_case.vozd.analytics import cache, service

router = APIRouter(prefix="/api/v1/vozd", tags=["Vozd analytics"], dependencies=[Depends(get_current_user)])

_SECTION_DOC = "Разделы через запятую: 1, 2, 3, 4 (без параметра — все)"


@router.get("/analytics/catalog", summary="Каталог метрик аналитики (разделы 1–4)")
async def analytics_catalog(
    section: str | None = Query(None, pattern="^[1-4]$", description="Только один раздел методики"),
) -> dict[str, Any]:
    """Все подпункты методики: id, название, тип (`auto` — считается, `llm` — гипотеза модели,
    `expert` — вводит эксперт), метрики-подсказки для экспертных пунктов. Значений здесь нет."""
    return service.catalog(section)


@router.get("/groups/{group_id}/analytics", summary="Последние рассчитанные значения аналитики по разделам")
async def analytics_cached(
    group_id: int = Path(..., ge=1),
    section: str | None = Query(None, description=_SECTION_DOC),
    metrics: str | None = Query(None, description="Только эти метрики (id через запятую), например 1.1,2.28"),
    window_days: int | None = Query(None, ge=1, le=3650, description="Окно расчёта: последние N дней (без окна — все данные)"),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    """Ничего не считает — отдаёт сохранённые результаты последнего расчёта.

    У каждой метрики: `status` (`computed`, `insufficient_data`, `not_available`, `failed`, `not_computed` —
    ещё не считалась, `expert`/`expert_pending` — экспертные), `value`, `computed_at` и признак `stale`
    (после расчёта появились новые данные сбора — `new_data` — или изменились чёрные списки — `blacklist_changed`).
    Окна `window_days` / `date_from`+`date_to` кэшируются отдельно. Поле `recalculation` — состояние фонового пересчёта."""
    return await cache.read_cached(
        db,
        group_id,
        cache.parse_sections(section),
        cache.window_key(window_days, date_from, date_to),
        cache.parse_metrics(metrics),
    )


@router.get("/groups/{group_id}/analytics/recalculate", summary="Пересчитать аналитику и сохранить в кэш")
async def analytics_recalculate(
    group_id: int = Path(..., ge=1),
    section: str | None = Query(None, description=_SECTION_DOC),
    metrics: str | None = Query(None, description="Пересчитать только эти метрики (id через запятую)"),
    include_llm: bool = Query(False, description="Считать и LLM-метрики (дольше и дороже; по умолчанию пропускаются, прежние значения остаются)"),
    wait: bool = Query(True, description="true — дождаться и вернуть новые значения; false — запустить в фоне (202), ход — GET …/analytics/status"),
    window_days: int | None = Query(None, ge=1, le=3650),
    date_from: datetime | None = Query(None),
    date_to: datetime | None = Query(None),
    sample_size: int = Query(200, ge=10, le=2000, description="Для LLM-метрик: сколько текстов брать (топ по вовлечённости)"),
    sample_recent_days: int = Query(7, ge=0, le=365, description="Для LLM-метрик: плюс все тексты за последние N дней"),
    provider: str | None = Query(None),
    model: str | None = Query(None),
    db: AsyncSession = Depends(get_vozd_session),
):
    """Пересчитывает метрики, сохраняет результат в кэш и (при `wait=true`) возвращает его в том же формате,
    что и `GET …/analytics`. Для экспертных пунктов заодно пересчитываются их метрики-подсказки.
    Если пересчёт для группы уже идёт — 409. Для больших групп и `include_llm=true` используйте `wait=false`."""
    await service._get_group(db, group_id)  # noqa: SLF001 — 404, если группы нет
    sections = cache.parse_sections(section)
    metric_ids = cache.parse_metrics(metrics)
    job = await cache.recalculate(
        group_id,
        wait=wait,
        sections=sections,
        metric_ids=metric_ids,
        include_llm=include_llm,
        window_days=window_days,
        date_from=date_from,
        date_to=date_to,
        sample_size=sample_size,
        sample_recent_days=sample_recent_days,
        provider=provider,
        model=model,
    )
    if not wait:
        return JSONResponse(status_code=202, content=job)
    return await cache.read_cached(db, group_id, sections, job["window"], metric_ids)


@router.get("/groups/{group_id}/analytics/status", summary="Состояние пересчёта аналитики")
async def analytics_status(group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)) -> dict[str, Any]:
    """`state`: idle | running | done | failed; `done`/`total` — прогресс по метрикам, `summary` — итог последнего пересчёта."""
    await service._get_group(db, group_id)  # noqa: SLF001
    return cache.job_state(group_id)


@router.get("/groups/{group_id}/analytics/compare", summary="Сравнить метрику «до» и «после»")
async def analytics_compare(
    group_id: int = Path(..., ge=1),
    metric: str = Query(..., description="ID метрики, например 3.14"),
    before: str = Query(..., description="Период «до»: YYYY-MM-DD..YYYY-MM-DD"),
    after: str = Query(..., description="Период «после»: YYYY-MM-DD..YYYY-MM-DD"),
    sample_size: int = Query(200, ge=10, le=2000),
    sample_recent_days: int = Query(7, ge=0, le=365),
    refresh: bool = Query(False),
    provider: str | None = Query(None),
    model: str | None = Query(None),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    """Универсальная обёртка «одна и та же метрика в двух периодах» с разницей числовых полей.
    Считается на лету и в кэш раздела не пишется."""
    return await service.compare(
        db, group_id, metric, before, after,
        sample_size=sample_size, sample_recent_days=sample_recent_days, refresh=refresh, provider=provider, model=model,
    )


@router.get("/groups/{group_id}/analytics/expert", summary="Все экспертные оценки группы")
async def analytics_expert_list(
    group_id: int = Path(..., ge=1), db: AsyncSession = Depends(get_vozd_session)
) -> dict[str, Any]:
    return await service.list_experts(db, group_id)


@router.put("/groups/{group_id}/analytics/{metric_id}/expert", summary="Сохранить экспертную оценку метрики")
async def analytics_expert_put(
    body: VozdAnalyticsExpertInput,
    group_id: int = Path(..., ge=1),
    metric_id: str = Path(..., description="ID метрики из каталога, например 4.3"),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    return await service.set_expert(db, group_id, metric_id, body.value, body.justification, body.expert)


@router.delete("/groups/{group_id}/analytics/{metric_id}/expert", summary="Удалить экспертную оценку метрики")
async def analytics_expert_delete(
    group_id: int = Path(..., ge=1),
    metric_id: str = Path(...),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    return await service.delete_expert(db, group_id, metric_id)
