"""
Scheduler API — /api/v1/scheduler
  GET    /rules                    – список правил расписания
  POST   /rules                    – создать правило
  GET    /rules/{rule_id}          – получить правило
  PATCH  /rules/{rule_id}          – обновить правило
  DELETE /rules/{rule_id}          – удалить правило
  POST   /rules/{rule_id}/enable   – включить правило
  POST   /rules/{rule_id}/disable  – отключить правило
  GET    /due                      – источники, готовые к сбору
  POST   /run-due                  – запустить все готовые источники
  POST   /recalculate              – пересчитать расписание
  GET    /timeline                 – будущие запуски
  GET    /logs                     – логи планировщика
  GET    /metrics                  – метрики
  GET    /state                    – состояние планировщика
  POST   /sources/{id}/trigger     – ручной запуск вне расписания
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Path, Query, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import JobType, TriggerType
from app.infrastructure.repositories.collection_job import (
    count_active_jobs_for_source,
    create_job,
    find_due_sources,
)
from app.infrastructure.repositories.schedule import add_schedule_log
from app.infrastructure.repositories.source import get_source_by_id
from app.presentation.api.dependencies import get_session
from app.presentation.schemas.collection_job import JobRead
from app.presentation.schemas.schedule import (
    DueSourceItem,
    DueSourcesResponse,
    RecalculateRequest,
    RecalculateResponse,
    RunDueResponse,
    ScheduleLogListResponse,
    ScheduleRuleCreateRequest,
    ScheduleRuleListResponse,
    ScheduleRuleRead,
    ScheduleRuleUpdateRequest,
    SchedulerMetrics,
    SchedulerState,
    UpcomingRunsResponse,
)
from app.use_case.schedule import logs as logs_uc
from app.use_case.schedule import metrics as metrics_uc
from app.use_case.schedule import recalculate as recalc_uc
from app.use_case.schedule import rules as rules_uc
from app.use_case.schedule import upcoming as upcoming_uc

router = APIRouter(prefix="/api/v1/scheduler", tags=["Scheduler"])


# ── Rules CRUD ─────────────────────────────────────────────────────────────


@router.get(
    "/rules",
    response_model=ScheduleRuleListResponse,
    summary="Список правил расписания",
)
async def list_rules(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=200),
    rule_type: str | None = Query(None),
    is_enabled: bool | None = Query(None),
    platform: str | None = Query(None),
    db: AsyncSession = Depends(get_session),
) -> ScheduleRuleListResponse:
    return await rules_uc.get_list(
        db,
        skip=skip,
        limit=limit,
        rule_type=rule_type,
        is_enabled=is_enabled,
        platform=platform,
    )


@router.post(
    "/rules",
    response_model=ScheduleRuleRead,
    status_code=status.HTTP_201_CREATED,
    summary="Создать правило расписания",
)
async def create_rule(
    body: ScheduleRuleCreateRequest,
    db: AsyncSession = Depends(get_session),
) -> ScheduleRuleRead:
    return await rules_uc.create(db, body)


@router.get(
    "/rules/{rule_id}",
    response_model=ScheduleRuleRead,
    summary="Получить правило по ID",
)
async def get_rule(
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> ScheduleRuleRead:
    return await rules_uc.get(db, rule_id)


@router.patch(
    "/rules/{rule_id}",
    response_model=ScheduleRuleRead,
    summary="Обновить правило",
)
async def patch_rule(
    rule_id: int = Path(..., ge=1),
    body: ScheduleRuleUpdateRequest = ...,
    db: AsyncSession = Depends(get_session),
) -> ScheduleRuleRead:
    return await rules_uc.patch(db, rule_id, body)


@router.delete(
    "/rules/{rule_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Удалить правило",
)
async def delete_rule(
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> Response:
    await rules_uc.remove(db, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/rules/{rule_id}/enable",
    response_model=ScheduleRuleRead,
    summary="Включить правило",
)
async def enable_rule(
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> ScheduleRuleRead:
    return await rules_uc.enable(db, rule_id)


@router.post(
    "/rules/{rule_id}/disable",
    response_model=ScheduleRuleRead,
    summary="Отключить правило",
)
async def disable_rule(
    rule_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> ScheduleRuleRead:
    return await rules_uc.disable(db, rule_id)


# ── Due sources ────────────────────────────────────────────────────────────


@router.get(
    "/due",
    response_model=DueSourcesResponse,
    summary="Источники, готовые к сбору (next_fetch_at ≤ now, нет активных задач)",
)
async def due_sources(
    db: AsyncSession = Depends(get_session),
) -> DueSourcesResponse:
    sources = await find_due_sources(db)
    items = [
        DueSourceItem(
            source_id=src.id,
            name=src.name,
            platform=src.source_type,
            url=src.url,
            next_fetch_at=src.next_fetch_at,
            last_success_at=src.last_success_at,
            error_count=src.error_count,
            priority=src.priority,
        )
        for src in sources
    ]
    return DueSourcesResponse(items=items, total=len(items))


@router.post(
    "/run-due",
    response_model=RunDueResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Запустить сбор по всем источникам, готовым к сбору",
)
async def run_due(
    db: AsyncSession = Depends(get_session),
) -> RunDueResponse:
    sources = await find_due_sources(db)
    job_ids: list[int] = []
    skipped = 0

    for src in sources:
        active = await count_active_jobs_for_source(db, src.id)
        if active > 0:
            skipped += 1
            continue
        job = await create_job(
            db,
            job_type=JobType.SCHEDULED_FETCH.value,
            source_id=src.id,
            trigger_type=TriggerType.MANUAL.value,
            priority=src.priority or 5,
        )
        await add_schedule_log(
            db,
            rule_id=None,
            source_id=src.id,
            job_id=job.id,
            trigger_reason="manual",
        )
        job_ids.append(job.id)

    return RunDueResponse(created=len(job_ids), skipped=skipped, job_ids=job_ids)


# ── Recalculate ────────────────────────────────────────────────────────────


@router.post(
    "/recalculate",
    response_model=RecalculateResponse,
    summary="Пересчитать next_fetch_at для источников",
)
async def recalculate(
    body: RecalculateRequest,
    db: AsyncSession = Depends(get_session),
) -> RecalculateResponse:
    return await recalc_uc.execute(db, body)


# ── Timeline ───────────────────────────────────────────────────────────────


@router.get(
    "/timeline",
    response_model=UpcomingRunsResponse,
    summary="Будущие запланированные запуски источников",
)
async def timeline(
    source_id: int | None = Query(None),
    limit_sources: int = Query(20, ge=1, le=100),
    runs_per_source: int = Query(5, ge=1, le=20),
    db: AsyncSession = Depends(get_session),
) -> UpcomingRunsResponse:
    return await upcoming_uc.execute(
        db,
        source_id=source_id,
        limit_sources=limit_sources,
        runs_per_source=runs_per_source,
    )


# ── Logs ───────────────────────────────────────────────────────────────────


@router.get(
    "/logs",
    response_model=ScheduleLogListResponse,
    summary="Логи планировщика",
)
async def scheduler_logs(
    source_id: int | None = Query(None),
    rule_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    db: AsyncSession = Depends(get_session),
) -> ScheduleLogListResponse:
    return await logs_uc.execute(
        db, source_id=source_id, rule_id=rule_id, skip=skip, limit=limit
    )


# ── Metrics & state ────────────────────────────────────────────────────────


@router.get(
    "/metrics",
    response_model=SchedulerMetrics,
    summary="Метрики планировщика",
)
async def scheduler_metrics(db: AsyncSession = Depends(get_session)) -> SchedulerMetrics:
    return await metrics_uc.get_metrics(db)


@router.get(
    "/state",
    response_model=SchedulerState,
    summary="Текущее состояние планировщика",
)
async def scheduler_state() -> SchedulerState:
    return metrics_uc.get_state()


# ── Manual trigger ─────────────────────────────────────────────────────────


@router.post(
    "/sources/{source_id}/trigger",
    response_model=JobRead,
    status_code=status.HTTP_201_CREATED,
    summary="Ручной запуск источника вне расписания",
)
async def trigger_source(
    source_id: int = Path(..., ge=1),
    db: AsyncSession = Depends(get_session),
) -> JobRead:
    src = await get_source_by_id(db, source_id)
    if src is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")

    job = await create_job(
        db,
        job_type=JobType.MANUAL_FETCH.value,
        source_id=source_id,
        trigger_type=TriggerType.MANUAL.value,
        priority=src.priority or 5,
    )
    await add_schedule_log(
        db,
        rule_id=None,
        source_id=source_id,
        job_id=job.id,
        trigger_reason="manual",
    )
    return JobRead.model_validate(job)
