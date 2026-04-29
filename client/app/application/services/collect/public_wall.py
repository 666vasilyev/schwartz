"""
Сбор постов со стены паблика VK: ссылка → owner_id (resolveScreenName), wall.get, нормализация.
Результат — id, текст, дата, реклама, вложения, реакции (лайки/репосты), комментарии.
"""
from __future__ import annotations

from typing import Any

from app.application.services.collect.vk_post_enrichment import (
    enrich_wall_posts_with_comments,
)
from app.core.config import get_settings
from app.infrastructure.vk import client as vk_client
from app.infrastructure.vk.vk_public_url import extract_screen_or_id_token
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_MOCK: list[dict] = [
    {
        "id": "mock_1",
        "owner_id": -1,
        "text": "MVP: пост с паблика (mock)",
    },
    {
        "id": "mock_2",
        "owner_id": -1,
        "text": "Второй mock-пост",
    },
]


def _owner_id_from_resolve(resp: dict) -> int:
    t = (resp.get("type") or "").lower()
    oid = int(resp.get("object_id", 0))
    if t in ("group", "page", "event"):
        return -oid
    if t == "user":
        return oid
    raise ValueError(
        f"utils.resolveScreenName: неподдерживаемый type={t!r} (нужен user/group/page/event)"
    )


async def resolve_wall_owner_id(path_segment: str) -> int:
    _token, precomputed = extract_screen_or_id_token(path_segment)
    if precomputed is not None:
        return precomputed
    res = await vk_client.resolve_screen_name(_token)
    if not res:
        raise ValueError("Пустой ответ resolveScreenName")
    return _owner_id_from_resolve(res)


def _mock_enriched_post(mock_id: str, owner_id: int, text: str | None) -> dict[str, Any]:
    return {
        "vk_post_id": str(mock_id),
        "owner_id": owner_id if owner_id else -1,
        "text": text,
        "published_at": None,
        "is_ad": False,
        "comments": [],
        "reactions": {"likes_count": 0, "reposts_count": 0},
        "attachments": [],
    }


async def collect_public_posts_for_ingest(
    *,
    owner_id: int,
    limit: int = 20,
    use_mock: bool = False,
) -> list[dict[str, Any]]:
    if use_mock or not (settings.vk_api_token and settings.vk_api_token.strip()):
        logger.info("vk_public_using_mock", owner_id=owner_id, limit=limit)
        return [
            _mock_enriched_post(str(p["id"]), owner_id if owner_id else -1, p.get("text"))
            for p in _MOCK[:limit]
        ]

    data = await vk_client.wall_get(owner_id=owner_id, count=limit)
    raw_items: list[dict] = data.get("items", []) if isinstance(data, dict) else []
    out = await enrich_wall_posts_with_comments(
        owner_id,
        raw_items,
        comments_per_post=settings.vk_comments_per_post,
        concurrency=settings.vk_comment_fetch_concurrency,
    )
    logger.info("vk_public_collected", owner_id=owner_id, n=len(out), limit=limit)
    return out
