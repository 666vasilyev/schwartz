"""CRUD use cases для source_categories."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from sqlalchemy import select

from app.infrastructure.db.orm.models import Source
from app.infrastructure.repositories.source_category import (
    create_category,
    delete_category,
    get_category,
    get_category_sources,
    list_categories,
    update_category,
)
from app.presentation.schemas.source import SourceRead
from app.presentation.schemas.source_category import (
    SourceCategoryCreateRequest,
    SourceCategoryListResponse,
    SourceCategoryRead,
    SourceCategoryUpdateRequest,
)


async def create(db: AsyncSession, body: SourceCategoryCreateRequest) -> SourceCategoryRead:
    existing = await get_category(db, body.name)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Категория с именем '{body.name}' уже существует",
        )
    obj = await create_category(db, name=body.name, description=body.description)
    await db.commit()
    return SourceCategoryRead.model_validate(obj)


async def list_all(
    db: AsyncSession, *, skip: int = 0, limit: int = 100
) -> SourceCategoryListResponse:
    items, total = await list_categories(db, skip=skip, limit=limit)
    return SourceCategoryListResponse(
        items=[SourceCategoryRead.model_validate(i) for i in items],
        total=total,
        skip=skip,
        limit=limit,
    )


async def get_by_name(db: AsyncSession, category_name: str) -> SourceCategoryRead:
    obj = await get_category(db, category_name)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    return SourceCategoryRead.model_validate(obj)


async def patch(
    db: AsyncSession, category_name: str, body: SourceCategoryUpdateRequest
) -> SourceCategoryRead:
    obj = await get_category(db, category_name)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    if body.name and body.name != obj.name:
        conflict = await get_category(db, body.name)
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Категория с именем '{body.name}' уже существует",
            )
    obj = await update_category(db, obj, name=body.name, description=body.description)
    await db.commit()
    return SourceCategoryRead.model_validate(obj)


async def get_sources(db: AsyncSession, category_name: str) -> list[SourceRead]:
    obj = await get_category(db, category_name)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    sources = await get_category_sources(db, category_name)
    return [SourceRead.model_validate(s) for s in sources]


async def _load_sources(db: AsyncSession, source_ids: list[int]) -> list[Source]:
    res = await db.execute(select(Source).where(Source.id.in_(source_ids)))
    return list(res.scalars().all())


async def attach_sources(db: AsyncSession, category_name: str, source_ids: list[int]) -> dict:
    """Привязывает список источников к категории (идемпотентно)."""
    obj = await get_category(db, category_name, load_sources=True)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    sources = await _load_sources(db, source_ids)
    found_ids = {s.id for s in sources}
    missing = [sid for sid in source_ids if sid not in found_ids]
    if missing:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Источники не найдены: {missing}",
        )
    # Добавляем только тех, кого ещё нет в категории
    existing_ids = {s.id for s in obj.sources}
    for src in sources:
        if src.id not in existing_ids:
            obj.sources.append(src)
    await db.commit()
    return {"attached": len(sources) - len(existing_ids & found_ids), "total": len(obj.sources)}


async def detach_sources(db: AsyncSession, category_name: str, source_ids: list[int]) -> dict:
    """Отвязывает список источников от категории."""
    obj = await get_category(db, category_name, load_sources=True)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    ids_to_remove = set(source_ids)
    before = len(obj.sources)
    obj.sources = [s for s in obj.sources if s.id not in ids_to_remove]
    await db.commit()
    return {"detached": before - len(obj.sources), "total": len(obj.sources)}


async def delete(db: AsyncSession, category_name: str) -> None:
    obj = await get_category(db, category_name)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    await delete_category(db, obj)
    await db.commit()
