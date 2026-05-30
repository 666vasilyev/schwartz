"""CRUD use cases для source_categories."""
from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.source_category import (
    create_category,
    delete_category,
    get_category,
    get_category_by_slug,
    list_categories,
    update_category,
)
from app.presentation.schemas.source_category import (
    SourceCategoryCreateRequest,
    SourceCategoryListResponse,
    SourceCategoryRead,
    SourceCategoryUpdateRequest,
)


async def create(db: AsyncSession, body: SourceCategoryCreateRequest) -> SourceCategoryRead:
    existing = await get_category_by_slug(db, body.slug)
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Категория со slug '{body.slug}' уже существует",
        )
    obj = await create_category(db, name=body.name, slug=body.slug, description=body.description)
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


async def get_by_id(db: AsyncSession, category_id: int) -> SourceCategoryRead:
    obj = await get_category(db, category_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    return SourceCategoryRead.model_validate(obj)


async def patch(
    db: AsyncSession, category_id: int, body: SourceCategoryUpdateRequest
) -> SourceCategoryRead:
    obj = await get_category(db, category_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    if body.slug and body.slug != obj.slug:
        conflict = await get_category_by_slug(db, body.slug)
        if conflict:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Категория со slug '{body.slug}' уже существует",
            )
    obj = await update_category(
        db, obj, name=body.name, slug=body.slug, description=body.description
    )
    await db.commit()
    return SourceCategoryRead.model_validate(obj)


async def delete(db: AsyncSession, category_id: int) -> None:
    obj = await get_category(db, category_id)
    if not obj:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Категория не найдена")
    await delete_category(db, obj)
    await db.commit()
