from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.schemas.source import BulkCreateRequest, BulkCreateResponse, SourceRead
from app.use_case.sources import post as post_uc


async def execute(db: AsyncSession, body: BulkCreateRequest) -> BulkCreateResponse:
    created: list[SourceRead] = []
    errors: list[dict] = []

    for i, src in enumerate(body.sources):
        try:
            async with db.begin_nested():  # savepoint per item
                result = await post_uc.execute(db, src)
            created.append(result)
        except Exception as exc:
            errors.append({"index": i, "url": src.url, "detail": str(exc)})

    return BulkCreateResponse(created=created, errors=errors)
