"""
Сырой сбор из VK: wall.get по owner_id (VK_WALL_OWNER_ID), без ленты рекомендаций.
Текст, дата, реклама, вложения, реакции, комментарии — для ответа collector.
"""
from __future__ import annotations

from typing import Any

from app.application.services.collect.vk_post_enrichment import (
    enrich_wall_posts_with_comments,
)
from app.core.config import get_settings
from app.infrastructure.repositories.vk_access_token import (
    vk_token_sources_configured_async,
)
from app.infrastructure.vk import client as vk_client
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

_MOCK: list[dict[str, Any]] = [
    {
        "vk_post_id": "90001",
        "owner_id": -1,
        "text": "MVP mock post A",
        "published_at": None,
        "is_ad": False,
        "comments": [],
        "reactions": {},
        "attachments": [],
    },
    {
        "vk_post_id": "90002",
        "owner_id": -1,
        "text": "MVP mock post B",
        "published_at": None,
        "is_ad": True,
        "comments": [],
        "reactions": {"likes_count": 3},
        "attachments": [{"type": "photo", "url": "https://example.com/p.jpg"}],
    },
    {
        "vk_post_id": "90003",
        "owner_id": 1,
        "text": "MVP mock post C",
        "published_at": None,
        "is_ad": False,
        "comments": [],
        "reactions": {},
        "attachments": [],
    },
]


async def collect_raw_posts(*, count: int, use_mock: bool) -> list[dict[str, Any]]:
    if use_mock or not await vk_token_sources_configured_async():
        logger.info("collect_using_mock", count=count)
        return list(_MOCK[: max(0, min(count, len(_MOCK)))])

    if settings.vk_wall_owner_id is None:
        logger.warning("collect_vk_no_owner", hint="set VK_WALL_OWNER_ID for wall.get")
        return []

    try:
        data = await vk_client.wall_get(
            owner_id=settings.vk_wall_owner_id, count=count
        )
    except Exception as exc:
        logger.warning("collect_vk_failed", error=str(exc))
        return []

    raw_items: list[dict] = data.get("items", []) if isinstance(data, dict) else []
    out = await enrich_wall_posts_with_comments(
        settings.vk_wall_owner_id,
        raw_items,
        comments_per_post=settings.vk_comments_per_post,
        concurrency=settings.vk_comment_fetch_concurrency,
    )
    logger.info("collect_vk_ok", n=len(out))
    return out
