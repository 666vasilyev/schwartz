"""
Раздел «Аналитика» проекта «воздействие» — /api/v1/vozd/analytics …

Универсальные ручки: метрики адресуются идентификатором из каталога (I.1, II.28, III.14 …), а не отдельными
эндпоинтами. Чёрные списки группы применяются ко всем расчётам.
"""
from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_current_user
from app.presentation.api.routes.vozd import get_vozd_session
from app.presentation.schemas.vozd import VozdAnalyticsExpertInput, VozdAnalyticsRequest
from app.use_case.vozd.analytics import service
from app.use_case.vozd.analytics.context import Window

router = APIRouter(prefix="/api/v1/vozd", tags=["Vozd analytics"], dependencies=[Depends(get_current_user)])


@router.get("/analytics/catalog", summary="Каталог метрик аналитики (разделы I–IV)")
async def analytics_catalog(
    section: str | None = Query(None, pattern="^(I|II|III|IV)$", description="Только один раздел методики"),
) -> dict[str, Any]:
    """Все подпункты методики: id, название, статус (`auto` — считается, `llm` — гипотеза модели,
    `expert` — вводит эксперт), метрики-подсказки для экспертных пунктов."""
    return service.catalog(section)


@router.post("/groups/{group_id}/analytics", summary="Рассчитать список метрик для группы")
async def analytics_compute(
    body: VozdAnalyticsRequest,
    group_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    """Один вызов — любое число метрик. Ошибка или нехватка данных одной метрики не мешает остальным:
    у каждой свой `status` (computed | insufficient_data | not_available | failed | expert | expert_pending)."""
    return await service.compute_metrics(
        db,
        group_id,
        body.metrics,
        window=Window.build(body.window_days, body.date_from, body.date_to),
        sample_size=body.sample_size,
        sample_recent_days=body.sample_recent_days,
        refresh=body.refresh,
        provider=body.provider,
        model=body.model,
    )


@router.get("/groups/{group_id}/analytics/compare", summary="Сравнить метрику «до» и «после»")
async def analytics_compare(
    group_id: int = Path(..., ge=1),
    metric: str = Query(..., description="ID метрики, например III.14"),
    before: str = Query(..., description="Период «до»: YYYY-MM-DD..YYYY-MM-DD"),
    after: str = Query(..., description="Период «после»: YYYY-MM-DD..YYYY-MM-DD"),
    sample_size: int = Query(200, ge=10, le=2000),
    sample_recent_days: int = Query(7, ge=0, le=365),
    refresh: bool = Query(False),
    provider: str | None = Query(None),
    model: str | None = Query(None),
    db: AsyncSession = Depends(get_vozd_session),
) -> dict[str, Any]:
    """Универсальная обёртка «одна и та же метрика в двух периодах» с разницей числовых полей."""
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
    metric_id: str = Path(..., description="ID метрики из каталога, например IV.3"),
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
