"""
Изоляция данных проектов (wall / vozd) на уровне сессии БД.

По умолчанию любая сессия видит только строки с project='wall' — так весь
существующий код wall (аналитика, кластеризация, леммы, экспорт, планировщик,
воркер, список источников и постов) продолжает работать ровно как раньше, даже
если в тех же таблицах лежат данные проекта «воздействие» (vozd).

Сессия проекта vozd явно включает свой scope: `use_project_scope(db, "vozd")`.
"""
from __future__ import annotations

from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Session, with_loader_criteria

PROJECT_WALL = "wall"
PROJECT_VOZD = "vozd"
INFO_KEY = "project_scope"

_registered = False


def use_project_scope(db: AsyncSession | Session, project: str) -> None:
    """Включить scope проекта для конкретной сессии."""
    sync = db.sync_session if isinstance(db, AsyncSession) else db
    sync.info[INFO_KEY] = project


def register_project_scope(post_cls: type, source_cls: type) -> None:
    """Вешает глобальный фильтр на ORM-SELECT'ы по Post и Source (идемпотентно)."""
    global _registered
    if _registered:
        return
    _registered = True

    @event.listens_for(Session, "do_orm_execute")
    def _apply_project_scope(state) -> None:  # noqa: ANN001
        if not state.is_select or state.is_column_load or state.is_relationship_load:
            return
        scope = state.session.info.get(INFO_KEY, PROJECT_WALL)
        state.statement = state.statement.options(
            with_loader_criteria(
                post_cls, post_cls.project == scope, include_aliases=True
            ),
            with_loader_criteria(
                source_cls, source_cls.project == scope, include_aliases=True
            ),
        )
