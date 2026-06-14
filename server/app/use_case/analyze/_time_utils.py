"""Утилиты для группировки дат по периодам (день / неделя / месяц)."""
from __future__ import annotations

from datetime import date, timedelta
from enum import Enum


class TimeGranularity(str, Enum):
    day = "day"
    week = "week"
    month = "month"


def period_start(d: date, granularity: TimeGranularity) -> date:
    """Начало периода, которому принадлежит дата d."""
    if granularity == TimeGranularity.day:
        return d
    if granularity == TimeGranularity.week:
        return d - timedelta(days=d.weekday())  # понедельник ISO-недели
    # month
    return date(d.year, d.month, 1)


def period_range(start: date, end: date, granularity: TimeGranularity) -> list[date]:
    """Список начал всех периодов в диапазоне [start, end] включительно."""
    periods: list[date] = []
    cur = period_start(start, granularity)
    end_anchor = period_start(end, granularity)
    while cur <= end_anchor:
        periods.append(cur)
        if granularity == TimeGranularity.day:
            cur += timedelta(days=1)
        elif granularity == TimeGranularity.week:
            cur += timedelta(weeks=1)
        else:  # month
            cur = date(cur.year + (cur.month == 12), cur.month % 12 + 1, 1)
    return periods
