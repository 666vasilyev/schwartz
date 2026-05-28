"""Import sources from uploaded JSON or CSV file."""
from __future__ import annotations

import csv
import io
import json
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.presentation.schemas.source import BulkCreateResponse, SourceCreateRequest, SourceRead, BulkCreateResponseErrors
from app.use_case.sources import post as post_uc

_MAX_ROWS = 500


async def execute(db: AsyncSession, file: UploadFile) -> BulkCreateResponse:
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".csv"):
        rows = _parse_csv(content)
    elif filename.endswith(".json") or file.content_type in ("application/json",):
        rows = _parse_json(content)
    else:
        # Try JSON first, fallback to CSV
        try:
            rows = _parse_json(content)
        except Exception:
            rows = _parse_csv(content)

    if len(rows) > _MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Максимум {_MAX_ROWS} источников за один импорт",
        )

    created: list[SourceRead] = []
    errors: list[dict] = []

    for i, row_data in enumerate(rows):
        try:
            async with db.begin_nested():  # savepoint per item — не откатывает всю транзакцию
                req = SourceCreateRequest.model_validate(row_data)
                result = await post_uc.execute(db, req)
            created.append(result)
        except Exception as exc:
            errors.append({"index": i, "data": row_data, "detail": str(exc)})
    if errors != []:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=errors,
        )
    return BulkCreateResponse(created=created)

def _parse_json(content: bytes) -> list[dict[str, Any]]:
    data = json.loads(content)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "sources" in data:
        return data["sources"]
    raise ValueError("JSON должен быть массивом или объектом с ключом 'sources'")


def _parse_csv(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        # Strip whitespace from all values
        clean = {k.strip(): v.strip() for k, v in row.items() if k and v.strip()}
        if clean:
            rows.append(clean)
    return rows
