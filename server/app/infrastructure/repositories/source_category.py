"""CRUD-репозиторий для source_categories."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.infrastructure.db.orm.models import Source, SourceCategoryModel


async def get_category(db: AsyncSession, name: str) -> SourceCategoryModel | None:
    res = await db.execute(
        select(SourceCategoryModel).where(SourceCategoryModel.name == name)
    )
    return res.scalar_one_or_none()


async def list_categories(
    db: AsyncSession, *, skip: int = 0, limit: int = 100
) -> tuple[list[SourceCategoryModel], int]:
    total_res = await db.execute(
        select(func.count()).select_from(SourceCategoryModel)
    )
    total = int(total_res.scalar_one())
    res = await db.execute(
        select(SourceCategoryModel)
        .order_by(SourceCategoryModel.name.asc())
        .offset(skip)
        .limit(limit)
    )
    return list(res.scalars().all()), total


async def create_category(
    db: AsyncSession,
    *,
    name: str,
    description: str | None,
) -> SourceCategoryModel:
    obj = SourceCategoryModel(name=name, description=description)
    db.add(obj)
    await db.flush()
    await db.refresh(obj)
    return obj


async def update_category(
    db: AsyncSession,
    obj: SourceCategoryModel,
    *,
    name: str | None = None,
    description: str | None = None,
) -> SourceCategoryModel:
    if name is not None:
        obj.name = name
    if description is not None:
        obj.description = description
    await db.flush()
    await db.refresh(obj)
    return obj


async def get_category_sources(db: AsyncSession, name: str) -> list[Source]:
    """Возвращает источники категории (только не удалённые)."""
    res = await db.execute(
        select(SourceCategoryModel)
        .options(selectinload(SourceCategoryModel.sources))
        .where(SourceCategoryModel.name == name)
    )
    obj = res.scalar_one_or_none()
    if obj is None:
        return []
    return [s for s in obj.sources if s.deleted_at is None]


async def delete_category(db: AsyncSession, obj: SourceCategoryModel) -> None:
    await db.delete(obj)
    await db.flush()
