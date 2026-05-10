"""Repository for ScheduleRule and ScheduleLog."""
from __future__ import annotations

from datetime import datetime, timezone

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.db.orm.models import ScheduleLog, ScheduleRule, ScheduleRuleType, Source


def _utcnow() -> datetime:
    return datetime.now(tz=timezone.utc)


# ── ScheduleRule CRUD ──────────────────────────────────────────────────────


async def create_rule(
    db: AsyncSession,
    *,
    rule_type: str,
    source_id: int | None = None,
    platform: str | None = None,
    group_name: str | None = None,
    base_interval_minutes: int = 60,
    min_interval_minutes: int = 5,
    max_interval_minutes: int = 10080,
    error_backoff_multiplier: float = 1.5,
    max_error_backoff_minutes: int = 480,
    priority_boost_enabled: bool = False,
    night_mode_enabled: bool = False,
    night_start_hour: int = 23,
    night_end_hour: int = 7,
    night_interval_minutes: int = 360,
    max_jobs_per_hour: int = 60,
    max_concurrent_jobs: int = 5,
    is_enabled: bool = True,
    description: str | None = None,
) -> ScheduleRule:
    rule = ScheduleRule(
        rule_type=rule_type,
        source_id=source_id,
        platform=platform,
        group_name=group_name,
        base_interval_minutes=base_interval_minutes,
        min_interval_minutes=min_interval_minutes,
        max_interval_minutes=max_interval_minutes,
        error_backoff_multiplier=error_backoff_multiplier,
        max_error_backoff_minutes=max_error_backoff_minutes,
        priority_boost_enabled=priority_boost_enabled,
        night_mode_enabled=night_mode_enabled,
        night_start_hour=night_start_hour,
        night_end_hour=night_end_hour,
        night_interval_minutes=night_interval_minutes,
        max_jobs_per_hour=max_jobs_per_hour,
        max_concurrent_jobs=max_concurrent_jobs,
        is_enabled=is_enabled,
        description=description,
    )
    db.add(rule)
    await db.flush()
    await db.refresh(rule)
    return rule


async def get_rule_by_id(db: AsyncSession, rule_id: int) -> ScheduleRule | None:
    return await db.get(ScheduleRule, rule_id)


async def list_rules(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    rule_type: str | None = None,
    is_enabled: bool | None = None,
    platform: str | None = None,
) -> list[ScheduleRule]:
    q = select(ScheduleRule).order_by(ScheduleRule.id)
    if rule_type:
        q = q.where(ScheduleRule.rule_type == rule_type)
    if is_enabled is not None:
        q = q.where(ScheduleRule.is_enabled == is_enabled)
    if platform:
        q = q.where(ScheduleRule.platform == platform)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_rules(
    db: AsyncSession,
    *,
    rule_type: str | None = None,
    is_enabled: bool | None = None,
) -> int:
    q = select(func.count()).select_from(ScheduleRule)
    if rule_type:
        q = q.where(ScheduleRule.rule_type == rule_type)
    if is_enabled is not None:
        q = q.where(ScheduleRule.is_enabled == is_enabled)
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def update_rule(db: AsyncSession, rule_id: int, **kwargs: object) -> ScheduleRule | None:
    rule = await get_rule_by_id(db, rule_id)
    if rule is None:
        return None
    for k, v in kwargs.items():
        setattr(rule, k, v)
    await db.flush()
    await db.refresh(rule)
    return rule


async def delete_rule(db: AsyncSession, rule_id: int) -> bool:
    rule = await get_rule_by_id(db, rule_id)
    if rule is None:
        return False
    await db.delete(rule)
    await db.flush()
    return True


# ── Rule resolution (specificity: source > group > platform) ───────────────


async def find_rule_for_source(db: AsyncSession, source: Source) -> ScheduleRule | None:
    """Return the most specific enabled rule for a source."""
    # 1. Source-specific
    if source.id:
        r = await db.scalar(
            select(ScheduleRule).where(
                ScheduleRule.rule_type == ScheduleRuleType.SOURCE,
                ScheduleRule.source_id == source.id,
                ScheduleRule.is_enabled.is_(True),
            )
        )
        if r:
            return r

    # 2. Group
    if source.schedule_group:
        r = await db.scalar(
            select(ScheduleRule).where(
                ScheduleRule.rule_type == ScheduleRuleType.GROUP,
                ScheduleRule.group_name == source.schedule_group,
                ScheduleRule.is_enabled.is_(True),
            )
        )
        if r:
            return r

    # 3. Platform
    if source.platform:
        r = await db.scalar(
            select(ScheduleRule).where(
                ScheduleRule.rule_type == ScheduleRuleType.PLATFORM,
                ScheduleRule.platform == source.platform,
                ScheduleRule.is_enabled.is_(True),
            )
        )
        if r:
            return r

    return None


# ── ScheduleLog ────────────────────────────────────────────────────────────


async def add_schedule_log(
    db: AsyncSession,
    *,
    rule_id: int | None,
    source_id: int | None,
    job_id: int | None,
    trigger_reason: str = "scheduled",
    calculated_interval_minutes: float | None = None,
    next_fetch_at: datetime | None = None,
) -> ScheduleLog:
    log = ScheduleLog(
        rule_id=rule_id,
        source_id=source_id,
        job_id=job_id,
        trigger_reason=trigger_reason,
        calculated_interval_minutes=calculated_interval_minutes,
        next_fetch_at=next_fetch_at,
        fired_at=_utcnow(),
    )
    db.add(log)
    await db.flush()
    return log


async def list_schedule_logs(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    rule_id: int | None = None,
    skip: int = 0,
    limit: int = 100,
) -> list[ScheduleLog]:
    q = select(ScheduleLog).order_by(ScheduleLog.fired_at.desc())
    if source_id is not None:
        q = q.where(ScheduleLog.source_id == source_id)
    if rule_id is not None:
        q = q.where(ScheduleLog.rule_id == rule_id)
    q = q.offset(skip).limit(limit)
    result = await db.execute(q)
    return list(result.scalars().all())


async def count_schedule_logs(
    db: AsyncSession,
    *,
    source_id: int | None = None,
    rule_id: int | None = None,
) -> int:
    q = select(func.count()).select_from(ScheduleLog)
    if source_id is not None:
        q = q.where(ScheduleLog.source_id == source_id)
    if rule_id is not None:
        q = q.where(ScheduleLog.rule_id == rule_id)
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


# ── Scheduler metrics helpers ──────────────────────────────────────────────


async def count_schedule_logs_since(db: AsyncSession, since: datetime) -> int:
    q = select(func.count()).select_from(ScheduleLog).where(ScheduleLog.fired_at >= since)
    r = await db.execute(q)
    return int(r.scalar_one() or 0)


async def count_schedule_logs_by_reason(
    db: AsyncSession, reason: str, since: datetime
) -> int:
    q = (
        select(func.count())
        .select_from(ScheduleLog)
        .where(ScheduleLog.trigger_reason == reason, ScheduleLog.fired_at >= since)
    )
    r = await db.execute(q)
    return int(r.scalar_one() or 0)
