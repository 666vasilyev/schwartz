"""CRUD use cases for ScheduleRule."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.schedule import (
    count_rules,
    create_rule,
    delete_rule,
    get_rule_by_id,
    list_rules,
    update_rule,
)
from app.infrastructure.repositories.source import get_source_by_id
from app.presentation.schemas.schedule import (
    ScheduleRuleCreateRequest,
    ScheduleRuleListResponse,
    ScheduleRuleRead,
    ScheduleRuleUpdateRequest,
)


async def create(db: AsyncSession, body: ScheduleRuleCreateRequest) -> ScheduleRuleRead:
    if body.rule_type == "source":
        if body.source_id is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="source_id обязателен для rule_type='source'",
            )
        src = await get_source_by_id(db, body.source_id)
        if src is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Источник не найден")
    elif body.rule_type == "platform":
        if not body.platform:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="platform обязателен для rule_type='platform'",
            )
    elif body.rule_type == "group":
        if not body.group_name:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail="group_name обязателен для rule_type='group'",
            )

    rule = await create_rule(
        db,
        rule_type=body.rule_type,
        source_id=body.source_id,
        platform=body.platform,
        group_name=body.group_name,
        base_interval_minutes=body.base_interval_minutes,
        min_interval_minutes=body.min_interval_minutes,
        max_interval_minutes=body.max_interval_minutes,
        error_backoff_multiplier=body.error_backoff_multiplier,
        max_error_backoff_minutes=body.max_error_backoff_minutes,
        priority_boost_enabled=body.priority_boost_enabled,
        night_mode_enabled=body.night_mode_enabled,
        night_start_hour=body.night_start_hour,
        night_end_hour=body.night_end_hour,
        night_interval_minutes=body.night_interval_minutes,
        max_jobs_per_hour=body.max_jobs_per_hour,
        max_concurrent_jobs=body.max_concurrent_jobs,
        is_enabled=body.is_enabled,
        description=body.description,
    )
    return ScheduleRuleRead.model_validate(rule)


async def get(db: AsyncSession, rule_id: int) -> ScheduleRuleRead:
    rule = await get_rule_by_id(db, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    return ScheduleRuleRead.model_validate(rule)


async def get_list(
    db: AsyncSession,
    *,
    skip: int = 0,
    limit: int = 50,
    rule_type: str | None = None,
    is_enabled: bool | None = None,
    platform: str | None = None,
) -> ScheduleRuleListResponse:
    rules = await list_rules(
        db, skip=skip, limit=limit, rule_type=rule_type, is_enabled=is_enabled, platform=platform
    )
    total = await count_rules(db, rule_type=rule_type, is_enabled=is_enabled)
    return ScheduleRuleListResponse(
        items=[ScheduleRuleRead.model_validate(r) for r in rules],
        total=total,
    )


async def patch(
    db: AsyncSession, rule_id: int, body: ScheduleRuleUpdateRequest
) -> ScheduleRuleRead:
    rule = await get_rule_by_id(db, rule_id)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")

    updates = {k: v for k, v in body.model_dump(exclude_unset=True).items() if v is not None}
    if updates:
        rule = await update_rule(db, rule_id, **updates)
    return ScheduleRuleRead.model_validate(rule)


async def enable(db: AsyncSession, rule_id: int) -> ScheduleRuleRead:
    rule = await update_rule(db, rule_id, is_enabled=True)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    return ScheduleRuleRead.model_validate(rule)


async def disable(db: AsyncSession, rule_id: int) -> ScheduleRuleRead:
    rule = await update_rule(db, rule_id, is_enabled=False)
    if rule is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
    return ScheduleRuleRead.model_validate(rule)


async def remove(db: AsyncSession, rule_id: int) -> None:
    found = await delete_rule(db, rule_id)
    if not found:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Правило не найдено")
