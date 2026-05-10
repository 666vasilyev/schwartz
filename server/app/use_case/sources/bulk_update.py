from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.schemas.source import BulkUpdateRequest, BulkUpdateResponse, SourceRead
from app.use_case.sources import patch as patch_uc


async def execute(db: AsyncSession, body: BulkUpdateRequest) -> BulkUpdateResponse:
    updated: list[SourceRead] = []
    errors: list[dict] = []

    for item in body.sources:
        try:
            async with db.begin_nested():  # savepoint per item
                result = await patch_uc.execute(db, item.id, item.data)
            updated.append(result)
        except Exception as exc:
            errors.append({"id": item.id, "detail": str(exc)})

    return BulkUpdateResponse(updated=updated, errors=errors)
