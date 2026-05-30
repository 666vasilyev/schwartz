"""Export posts to JSON or CSV."""
from __future__ import annotations

import csv
import io
import json
from datetime import datetime

from fastapi.responses import Response, StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.repositories.post import list_posts
from app.presentation.schemas.post import PostRead
from app.use_case.posts.get_all import _build_post_url

_EXPORT_LIMIT = 50_000

_CSV_FIELDS = [
    "id", "source_id", "source_type", "url", "external_id",
    "text", "published_at", "is_ad", "created_at",
]


async def execute(
    db: AsyncSession,
    *,
    fmt: str = "json",
    source_id: int | None = None,
    category_ids: list[int] | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    search: str | None = None,
) -> Response:
    rows = await list_posts(
        db,
        skip=0,
        limit=_EXPORT_LIMIT,
        source_id=source_id,
        category_ids=category_ids,
        date_from=date_from,
        date_to=date_to,
        search=search,
    )
    items = []
    for post, source_type, source_url in rows:
        data = PostRead.model_validate(post)
        data.source_type = source_type
        data.url = _build_post_url(post, source_type, source_url)
        items.append(data)

    if fmt == "csv":
        return _to_csv(items)
    return _to_json(items)


def _to_json(items: list[PostRead]) -> Response:
    data = [item.model_dump(mode="json") for item in items]
    body = json.dumps({"posts": data, "total": len(data)}, ensure_ascii=False, default=str)
    return Response(
        content=body,
        media_type="application/json",
        headers={"Content-Disposition": "attachment; filename=posts.json"},
    )


def _to_csv(items: list[PostRead]) -> StreamingResponse:
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
        headers={"Content-Disposition": "attachment; filename=posts.csv"},
    )
