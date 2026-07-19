"""
GET /api/v1/clusters/trending — единый эндпоинт трендов (live + ретроспектива).

source_ids и category_names — необязательные списки (могут быть пустыми):
  - оба пусты → общие тренды по всем источникам;
  - задан только один → тренд в рамках этого множества (union внутри списка);
  - заданы оба → тренд по пересечению (AND) — источник должен одновременно
    входить в source_ids И относиться хотя бы к одной из category_names.

as_of переключает режим на ретроспективу: тренды за window_days суток, начиная
с as_of, посчитанные по дате публикации постов (а не по времени их обработки
пайплайном) и без фильтра "кластер сейчас активен" — иначе почти все кластеры
за прошлый период уже archived и результат был бы пустым. См. подробный
докстринг list_trending_combined про допущения этого режима.
"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from sqlalchemy.ext.asyncio import AsyncSession

from app.application.services.content.lemma_scorer import LemmaLang
from app.infrastructure.repositories import list_trending_combined
from app.presentation.schemas.cluster import TrendingClustersResponse
from app.use_case.clusters._trending_common import build_trending_items
from app.utils.date_range import utc_window


async def execute(
    db: AsyncSession,
    *,
    source_ids: list[int] | None = None,
    category_names: list[str] | None = None,
    window_hours: int = 24,
    min_posts: int = 3,
    limit: int = 20,
    as_of: date | None = None,
    window_days: int = 1,
    lemma_lang: LemmaLang = LemmaLang.ru,
    lemma_top_n: int = 10,
) -> TrendingClustersResponse:
    source_ids = source_ids or []
    category_names = category_names or []

    if as_of is not None:
        # Ретроспектива: окно — календарные сутки as_of (и window_days вперёд
        # от него), считаем по published_at, статус кластера не важен.
        window_start, anchor_now = utc_window(as_of, window_days)
        effective_window_hours = window_days * 24
        rows = await list_trending_combined(
            db,
            source_ids=source_ids or None,
            category_names=category_names or None,
            window_hours=effective_window_hours,
            min_posts=min_posts,
            limit=limit,
            now=anchor_now,
            use_published_at=True,
            require_active=False,
        )
        window_end = anchor_now
    else:
        # now считается один раз и передаётся явно (now=window_end) — иначе
        # list_trending_combined взял бы свой собственный _utcnow() чуть позже,
        # и окно отбора кластеров могло бы на миллисекунды разойтись с окном,
        # которое используется здесь же для подсчёта new_lemmas.
        effective_window_hours = window_hours
        window_end = datetime.now(tz=timezone.utc)
        window_start = window_end - timedelta(hours=window_hours)
        rows = await list_trending_combined(
            db,
            source_ids=source_ids or None,
            category_names=category_names or None,
            window_hours=window_hours,
            min_posts=min_posts,
            limit=limit,
            now=window_end,
        )

    items = await build_trending_items(
        db,
        rows,
        window_start=window_start,
        window_end=window_end,
        lemma_lang=lemma_lang,
        lemma_top_n=lemma_top_n,
    )
    return TrendingClustersResponse(
        items=items,
        window_hours=effective_window_hours,
        min_posts=min_posts,
        source_ids=source_ids,
        category_names=category_names,
        as_of=as_of,
    )
