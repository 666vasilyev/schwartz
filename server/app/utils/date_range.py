"""
Общие хелперы для перевода "дата/период" в UTC-границы datetime — чтобы окна
запросов к БД не разъезжались между местами, которые их строят вручную.

Два разных паттерна, которые здесь встречаются:
  - utc_window: полуоткрытое окно [start_date 00:00; start_date+days 00:00) —
    для ретроспективных trending-окон (/clusters/trending?as_of=,
    use_case/analyze/lemma_trend_candidates.py).
  - utc_day_range: включительный календарный диапазон [date_from 00:00;
    date_to 23:59:59.999999] — для фильтров "за период" в аналитике
    (use_case/analytics/*).
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone


def utc_window(start_date: date, days: int) -> tuple[datetime, datetime]:
    """Полуоткрытое окно в UTC: [start_date 00:00; start_date + days 00:00)."""
    start = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=days)
    return start, end


def utc_day_start(d: date) -> datetime:
    """00:00:00.000000 указанной даты в UTC — начало календарных суток."""
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


def utc_day_end(d: date) -> datetime:
    """23:59:59.999999 указанной даты в UTC — конец календарных суток (включительно)."""
    return datetime.combine(d, time.max, tzinfo=timezone.utc)


def utc_day_range(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    """Включительный диапазон в UTC: [date_from 00:00; date_to 23:59:59.999999]."""
    return utc_day_start(date_from), utc_day_end(date_to)
