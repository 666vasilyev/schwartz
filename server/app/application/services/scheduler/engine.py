"""
Schedule engine: pure calculation functions for next_fetch_at.

Priority model (lower int = higher priority):
  priority 1 → 50 % reduction of interval
  priority 5 → no change (default)
  priority 10 → no change (default, not boosted down)
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.infrastructure.db.orm.models import ScheduleRule, Source


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


def _in_night_window(hour: int, night_start: int, night_end: int) -> bool:
    """True when `hour` falls inside [night_start, night_end) (wraps midnight)."""
    if night_start == night_end:
        return False
    if night_start > night_end:  # wraps: e.g. 23-7
        return hour >= night_start or hour < night_end
    return night_start <= hour < night_end  # simple range


def calculate_interval(
    source: "Source",
    rule: "ScheduleRule | None",
    *,
    last_duration_ms: int | None = None,
    now: datetime | None = None,
) -> float:
    """
    Return the collection interval in minutes, incorporating all rules.
    """
    if now is None:
        now = _utcnow()

    # Base values (from rule or source default)
    base: float = float(source.fetch_interval_minutes or 60)
    min_int: float = 5.0
    max_int: float = 10080.0  # 1 week

    backoff_mult: float = 1.5
    max_backoff: float = 480.0

    night_enabled = False
    night_start = 23
    night_end = 7
    night_interval: float = 360.0

    priority_boost = False

    if rule is not None:
        base = float(rule.base_interval_minutes)
        min_int = float(rule.min_interval_minutes)
        max_int = float(rule.max_interval_minutes)
        backoff_mult = float(rule.error_backoff_multiplier)
        max_backoff = float(rule.max_error_backoff_minutes)
        night_enabled = rule.night_mode_enabled
        night_start = rule.night_start_hour
        night_end = rule.night_end_hour
        night_interval = float(rule.night_interval_minutes)
        priority_boost = rule.priority_boost_enabled

    interval = base

    # ── Error backoff: multiply interval per consecutive error ─────────────
    error_count = source.error_count or 0
    if error_count > 0:
        multiplied = base * (backoff_mult ** error_count)
        interval = min(multiplied, max_backoff)

    # ── Priority boost: reduce interval for high-priority (low int) sources ─
    # priority 1 → 50 % of interval; priority 5 → 100 %; >5 → no reduction
    if priority_boost:
        prio = source.priority or 5
        if 1 <= prio < 5:
            reduction = 0.5 + (prio - 1) * 0.125  # 0.5 at prio=1 … 1.0 at prio=5
            interval = max(interval * reduction, min_int)

    # ── Duration awareness: add 30 % of previous job duration ─────────────
    if last_duration_ms and last_duration_ms > 0:
        duration_minutes = last_duration_ms / 1000.0 / 60.0
        interval += duration_minutes * 0.3

    # ── Night mode: floor to night_interval during off-hours ──────────────
    if night_enabled and _in_night_window(now.hour, night_start, night_end):
        interval = max(interval, night_interval)

    return max(min_int, min(interval, max_int))


def calculate_next_fetch_at(
    source: "Source",
    rule: "ScheduleRule | None",
    *,
    last_duration_ms: int | None = None,
    now: datetime | None = None,
) -> datetime:
    if now is None:
        now = _utcnow()
    interval = calculate_interval(source, rule, last_duration_ms=last_duration_ms, now=now)
    return now + timedelta(minutes=interval)


def preview_upcoming(
    source: "Source",
    rule: "ScheduleRule | None",
    *,
    count: int = 5,
    now: datetime | None = None,
) -> list[datetime]:
    """Return a list of upcoming scheduled datetimes for a source."""
    if now is None:
        now = _utcnow()
    timestamps: list[datetime] = []
    cursor = source.next_fetch_at or now
    for _ in range(count):
        interval = calculate_interval(source, rule, now=cursor)
        cursor = cursor + timedelta(minutes=interval)
        timestamps.append(cursor)
    return timestamps
