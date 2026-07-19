"""Схемы API для страницы "Аналитика" — /api/v1/analytics."""
from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field


class PostsCollectedStatsResponse(BaseModel):
    """
    Статистика СОБРАННЫХ постов — по created_at (момент сохранения в БД нашим
    пайплайном), а не published_at (дата публикации на источнике, может быть
    в прошлом при историческом сборе).
    """

    as_of: datetime = Field(description="Момент расчёта (UTC)")
    last_24h: int = Field(description="Собрано постов за последние 24 часа")
    last_7d: int = Field(description="Собрано постов за последние 7 суток")
    last_30d: int = Field(description="Собрано постов за последние 30 суток")
    total: int = Field(description="Всего постов в системе")


class PostsDailyPoint(BaseModel):
    date: date
    count: int = Field(description="Собрано постов за эту дату (по created_at)")


class PostsDailyResponse(BaseModel):
    """Динамика собранных постов по дням — данные для графика."""

    date_from: date
    date_to: date
    points: list[PostsDailyPoint] = Field(
        default_factory=list,
        description="По одной точке на каждый день диапазона (дни без постов — count=0)",
    )


class SourceCountsResponse(BaseModel):
    """Количество источников СМИ: всего и в разбивке по статусу/типу."""

    total: int = Field(description="Всего источников (без удалённых)")
    by_status: dict[str, int] = Field(
        default_factory=dict, description="active/paused/disabled/error/blocked -> количество"
    )
    by_type: dict[str, int] = Field(default_factory=dict, description="vk/rss/telegram -> количество")


class TopSourceItem(BaseModel):
    source_id: int
    source_name: str | None = None
    source_type: str | None = None
    posts_count: int = Field(description="Собрано постов от этого источника за период")


class TopSourcesResponse(BaseModel):
    """
    Топ источников по числу собранных постов за период — собственное
    предложение: показывает, кто реально поставляет больше всего контента,
    дополняя общие счётчики постов/источников конкретной раскладкой по вкладу.
    """

    date_from: date | None = Field(default=None, description="Начало диапазона (по created_at); null — за всё время")
    date_to: date | None = Field(default=None, description="Конец диапазона (по created_at); null — за всё время")
    items: list[TopSourceItem] = Field(default_factory=list, description="Отсортировано по убыванию posts_count")
