"""
Analytics API — /api/v1/analytics

Питает страницу "Аналитика":
  GET /posts/stats    — статистика собранных постов (24ч / 7д / 30д / всего)
  GET /posts/daily    — динамика: собранные посты по дням (для графика)
  GET /sources/counts — количество источников СМИ (всего + по статусу/типу)
  GET /sources/top    — топ источников по числу собранных постов за период
                        (собственное предложение, см. use_case/analytics/top_sources.py)
"""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.api.dependencies import get_session
from app.presentation.schemas.analytics import (
    PostsCollectedStatsResponse,
    PostsDailyResponse,
    SourceCountsResponse,
    TopSourcesResponse,
)
from app.use_case.analytics import posts_daily as posts_daily_uc
from app.use_case.analytics import posts_stats as posts_stats_uc
from app.use_case.analytics import sources_counts as sources_counts_uc
from app.use_case.analytics import top_sources as top_sources_uc

router = APIRouter(prefix="/api/v1/analytics", tags=["Analytics"])


@router.get(
    "/posts/stats",
    response_model=PostsCollectedStatsResponse,
    summary="Статистика собранных постов: за сутки / неделю / месяц / всего",
)
async def get_posts_stats(
    db: AsyncSession = Depends(get_session),
) -> PostsCollectedStatsResponse:
    return await posts_stats_uc.execute(db)


@router.get(
    "/posts/daily",
    response_model=PostsDailyResponse,
    summary="Динамика собранных постов по дням (данные для графика)",
)
async def get_posts_daily(
    date_from: date | None = Query(None, description="Начало диапазона (по умолчанию — 29 дней назад)"),
    date_to: date | None = Query(None, description="Конец диапазона (по умолчанию — сегодня, UTC)"),
    db: AsyncSession = Depends(get_session),
) -> PostsDailyResponse:
    dt_to = date_to or date.today()
    dt_from = date_from or (dt_to - timedelta(days=29))
    return await posts_daily_uc.execute(db, date_from=dt_from, date_to=dt_to)


@router.get(
    "/sources/counts",
    response_model=SourceCountsResponse,
    summary="Количество источников СМИ: всего и в разбивке по статусу/типу",
)
async def get_sources_counts(
    db: AsyncSession = Depends(get_session),
) -> SourceCountsResponse:
    return await sources_counts_uc.execute(db)


@router.get(
    "/sources/top",
    response_model=TopSourcesResponse,
    summary="Топ источников по числу собранных постов за период",
)
async def get_top_sources(
    limit: int = Query(10, ge=1, le=100),
    date_from: date | None = Query(None, description="Начало диапазона (по created_at); пусто — за всё время"),
    date_to: date | None = Query(None, description="Конец диапазона (по created_at); пусто — за всё время"),
    db: AsyncSession = Depends(get_session),
) -> TopSourcesResponse:
    return await top_sources_uc.execute(db, limit=limit, date_from=date_from, date_to=date_to)
