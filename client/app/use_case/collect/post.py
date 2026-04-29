from __future__ import annotations

from app.application.services.collect.raw_wall import collect_raw_posts
from app.presentation.schemas.collector import CollectRequest, CollectResponse


async def execute(body: CollectRequest) -> CollectResponse:
    posts = await collect_raw_posts(count=body.count, use_mock=body.use_mock)
    return CollectResponse(collected=len(posts), posts=posts)
