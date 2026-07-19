"""
Clusters API — /api/v1/clusters

Эндпоинты:
  GET    /api/v1/clusters                 — список сюжетов с фильтрами
  GET    /api/v1/clusters/trending        — трендовые сюжеты: live (по умолчанию)
                                             или ретроспектива на дату (as_of),
                                             опционально по source_ids и/или
                                             category_names
  GET    /api/v1/clusters/{id}            — карточка сюжета + посты
  POST   /api/v1/clusters/run             — один тик инкрементальной кластеризации
  POST   /api/v1/clusters/rebuild         — полная перестройка (медленно)
  POST   /api/v1/clusters/{id}/label      — обновить title/summary/topics через LLM
"""
from __future__ import annotations

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang
from app.infrastructure.db.orm.models import StoryClusterStatus
from app.presentation.api.dependencies import get_session
from app.presentation.schemas.cluster import (
    ClusterDetailResponse,
    ClusterListResponse,
    ClusterRead,
    ClusterRebuildResponse,
    ClusterRunResponse,
    TrendingClustersResponse,
)
from app.use_case.clusters import (
    get_cluster as get_cluster_uc,
    label_cluster as label_cluster_uc,
    list_clusters as list_clusters_uc,
    rebuild as rebuild_uc,
    run_cycle as run_cycle_uc,
    trending as trending_uc,
)

router = APIRouter(prefix="/api/v1/clusters", tags=["Clusters"])


@router.get(
    "",
    response_model=ClusterListResponse,
    summary="Список сюжетных кластеров с фильтрами",
)
async def list_clusters_endpoint(
    skip: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=200),
    status: StoryClusterStatus | None = Query(
        StoryClusterStatus.ACTIVE,
        description="Статус сюжета: active | archived",
    ),
    min_posts: int | None = Query(
        None, ge=1, description="Минимум постов в сюжете"
    ),
    date_from: datetime | None = Query(
        None, description="last_seen_at >= (включительно)"
    ),
    date_to: datetime | None = Query(
        None, description="last_seen_at <= (включительно)"
    ),
    db: AsyncSession = Depends(get_session),
) -> ClusterListResponse:
    return await list_clusters_uc.execute(
        db,
        skip=skip,
        limit=limit,
        status=status.value if status else None,
        min_posts=min_posts,
        date_from=date_from,
        date_to=date_to,
    )


@router.get(
    "/trending",
    response_model=TrendingClustersResponse,
    summary="Трендовые сюжеты за окно (по приросту постов)",
)
async def trending_endpoint(
    source_ids: list[int] = Query(
        default=[],
        description=(
            "Опционально: один или несколько ID источников "
            "(?source_ids=1&source_ids=2 — union внутри списка). "
            "Пусто — без фильтра по источнику."
        ),
    ),
    category_names: list[str] = Query(
        default=[],
        description=(
            "Опционально: одна или несколько категорий источников "
            "(?category_names=tech&category_names=politics — union внутри списка). "
            "Пусто — без фильтра по категории."
        ),
    ),
    window_hours: int = Query(
        24,
        ge=1,
        le=168,
        description="Live-режим (as_of не задан): окно в часах назад от текущего момента (макс 7 дней)",
    ),
    min_posts: int = Query(3, ge=1, description="Минимум постов в окне"),
    limit: int = Query(20, ge=1, le=200),
    as_of: date | None = Query(
        None,
        description=(
            "Ретроспектива: тренды за window_days суток начиная с этой даты "
            "(UTC), посчитанные по дате публикации постов. Если задано — "
            "window_hours игнорируется, используется window_days."
        ),
    ),
    window_days: int = Query(
        1,
        ge=1,
        le=90,
        description="Ширина окна ретроспективы в сутках от as_of (используется только вместе с as_of)",
    ),
    lemma_lang: LemmaLang = Query(
        LemmaLang.ru,
        description="Словарь для new_lemmas (только чёрный список — сами леммы не скорятся): ru, ru_un, usa, usa_un, frg",
    ),
    lemma_top_n: int = Query(
        10, ge=0, le=50, description="Сколько самых частых лемм на кластер отдавать в new_lemmas (0 — не считать)"
    ),
    db: AsyncSession = Depends(get_session),
) -> TrendingClustersResponse:
    """
    Live-режим (as_of не задан) — без параметров общие тренды по всем
    источникам за последние window_hours; с source_ids и/или category_names —
    в рамках этих множеств (пересечение AND, если заданы оба).

    Ретроспектива (as_of задан) — то же самое, но окно [as_of; as_of+window_days)
    считается по дате публикации постов, без фильтра "кластер сейчас активен".
    Кластеры — стейтфул объекты, поэтому это посты даты X, сгруппированные по
    ИХ ТЕКУЩЕЙ принадлежности к кластеру, а не точная картина live-запроса
    в тот день (см. list_trending_combined).

    new_lemmas на каждом элементе — самые частые леммы в постах ЭТОГО кластера
    за то же окно (простой список, как topics); леммы из чёрного списка
    (/lemma/blacklist) исключены.
    """
    return await trending_uc.execute(
        db,
        source_ids=source_ids,
        category_names=category_names,
        window_hours=window_hours,
        min_posts=min_posts,
        limit=limit,
        as_of=as_of,
        window_days=window_days,
        lemma_lang=lemma_lang,
        lemma_top_n=lemma_top_n,
    )


@router.get(
    "/{cluster_id}",
    response_model=ClusterDetailResponse,
    summary="Детали сюжета + посты",
)
async def get_cluster_endpoint(
    cluster_id: int,
    posts_skip: int = Query(0, ge=0),
    posts_limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_session),
) -> ClusterDetailResponse:
    return await get_cluster_uc.execute(
        db,
        cluster_id,
        posts_skip=posts_skip,
        posts_limit=posts_limit,
    )


@router.post(
    "/run",
    response_model=ClusterRunResponse,
    summary="Один цикл инкрементальной кластеризации (берёт N постов без эмбеддинга)",
)
async def run_cycle_endpoint(
    db: AsyncSession = Depends(get_session),
) -> ClusterRunResponse:
    return await run_cycle_uc.execute(db)


@router.post(
    "/rebuild",
    response_model=ClusterRebuildResponse,
    summary="Полная перестройка сюжетов (очищает кластеры, оставляет эмбеддинги)",
)
async def rebuild_endpoint(
    clear: bool = Query(
        True,
        description=(
            "true — сначала очистить все кластеры и назначения, "
            "false — просто догнать необработанные посты"
        ),
    ),
    db: AsyncSession = Depends(get_session),
) -> ClusterRebuildResponse:
    return await rebuild_uc.execute(db, clear=clear)


@router.post(
    "/{cluster_id}/label",
    response_model=ClusterRead,
    summary="Сгенерировать title/summary/topics через LLM",
)
async def label_cluster_endpoint(
    cluster_id: int,
    db: AsyncSession = Depends(get_session),
) -> ClusterRead:
    return await label_cluster_uc.execute(db, cluster_id)
