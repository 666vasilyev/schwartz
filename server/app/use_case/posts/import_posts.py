"""Import posts from uploaded JSON or CSV file."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime
from typing import Any

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.post import save_post
from app.presentation.schemas.post import PostRead

_MAX_ROWS = 10_000


async def execute(db: AsyncSession, file: UploadFile) -> dict:
    content = await file.read()
    filename = (file.filename or "").lower()

    if filename.endswith(".csv"):
        rows = _parse_csv(content)
    elif filename.endswith(".json") or file.content_type == "application/json":
        rows = _parse_json(content)
    else:
        try:
            rows = _parse_json(content)
        except Exception:
            rows = _parse_csv(content)

    if len(rows) > _MAX_ROWS:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Максимум {_MAX_ROWS} постов за один импорт",
        )

    created: list[PostRead] = []
    errors: list[dict] = []

    for i, row_data in enumerate(rows):
        try:
            async with db.begin_nested():
                post = await save_post(db, _normalize_row(row_data))
            created.append(PostRead.model_validate(post))
        except Exception as exc:
            errors.append({"index": i, "detail": str(exc)})

    return {"created": len(created), "errors": errors}


def _normalize_row(row: dict[str, Any]) -> dict[str, Any]:
    """Привести строку CSV/JSON к dict для save_post."""
    result: dict[str, Any] = {}

    for key in ("source_id", "external_id", "vk_post_id", "text", "is_ad", "reactions", "attachments", "payload"):
        if key in row and row[key] not in (None, ""):
            result[key] = row[key]

    if "source_id" in result:
        try:
            result["source_id"] = int(result["source_id"])
        except (ValueError, TypeError):
            result.pop("source_id", None)

    if "published_at" in row and row["published_at"]:
        try:
            result["published_at"] = datetime.fromisoformat(str(row["published_at"]))
        except ValueError:
            pass

    if "owner_id" in row and row["owner_id"] not in (None, ""):
        try:
            result["owner_id"] = int(row["owner_id"])
        except (ValueError, TypeError):
            pass

    return result


def _parse_json(content: bytes) -> list[dict[str, Any]]:
    data = json.loads(content)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and "posts" in data:
        return data["posts"]
    raise ValueError("JSON должен быть массивом или объектом с ключом 'posts'")


def _parse_csv(content: bytes) -> list[dict[str, Any]]:
    text = content.decode("utf-8-sig")
    reader = csv.DictReader(io.StringIO(text))
    rows = []
    for row in reader:
        clean = {k.strip(): v.strip() for k, v in row.items() if k and v.strip()}
        if clean:
            rows.append(clean)
    return rows
