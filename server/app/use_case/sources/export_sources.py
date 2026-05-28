"""Export sources to JSON or CSV."""
from __future__ import annotations

import csv
import io

from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories import list_sources
from app.presentation.schemas.source import SourceRead

_EXPORT_LIMIT = 10_000

_CSV_FIELDS = [
    "id", "name", "url", "source", "source_type", "platform", "username",
    "external_id", "description", "status", "priority", "fetch_interval_minutes",
    "language_hint", "region_hint", "topic_hint", "owner_id",
    "error_count", "auth_required", "created_at", "updated_at",
]


async def execute(
    db: AsyncSession,
    *,
    fmt: str = "json",
    status_filter: str | None = None,
    platform_filter: str | None = None,
) -> Response:
    rows = await list_sources(
        db,
        skip=0,
        limit=_EXPORT_LIMIT,
        status=status_filter,
        platform=platform_filter,
    )
    items = [SourceRead.model_validate(r) for r in rows]

    if fmt == "csv":
        return _to_csv(items)
    return _to_json(items)


def _to_json(items: list[SourceRead]) -> Response:
    import json

    data = [item.model_dump(mode="json") for item in items]
    body = json.dumps({"sources": data, "total": len(data)}, ensure_ascii=False, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=sources.json"},
    )


def _to_csv(items: list[SourceRead]) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=_CSV_FIELDS, extrasaction="ignore")
    writer.writeheader()
    for item in items:
        d = item.model_dump(mode="json")
        writer.writerow({k: d.get(k, "") for k in _CSV_FIELDS})

    buf.seek(0)

    def _iter():
        yield buf.read().encode("utf-8")

    return StreamingResponse(
        _iter(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sources.csv"},
    )
