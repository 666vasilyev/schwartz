from fastapi import APIRouter, Depends

from app.presentation.api.dependencies import require_collector_auth
from app.presentation.schemas.collector import (
    CollectRequest,
    CollectResponse,
    PublicCollectRequest,
    PublicCollectResponse,
    RssCollectRequest,
    RssCollectResponse,
)
from app.use_case.collect import post as collect_post
from app.use_case.collect import post_public as collect_post_public
from app.use_case.collect import post_rss as collect_post_rss

router = APIRouter(tags=["Collect"])


@router.post(
    "/collect",
    response_model=CollectResponse,
    summary="Собрать посты (только VK → JSON)",
    dependencies=[Depends(require_collector_auth)],
)
async def collect(body: CollectRequest) -> CollectResponse:
    return await collect_post.execute(body)


@router.post(
    "/collect/public",
    response_model=PublicCollectResponse,
    summary="Стена паблика по ссылке (только VK → JSON для сервера)",
    dependencies=[Depends(require_collector_auth)],
)
async def collect_public(body: PublicCollectRequest) -> PublicCollectResponse:
    return await collect_post_public.execute(body)


@router.post(
    "/collect/rss",
    response_model=RssCollectResponse,
    summary="RSS/Atom лента по URL → JSON для оркестрации",
    dependencies=[Depends(require_collector_auth)],
)
async def collect_rss(body: RssCollectRequest) -> RssCollectResponse:
    return await collect_post_rss.execute(body)
