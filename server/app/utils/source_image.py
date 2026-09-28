"""
Общая логика картинки поста: своя (из attachments) или fallback на картинку
источника — см. server/app/infrastructure/repositories/post.py (list_posts),
server/app/use_case/posts/get_all.py, server/app/use_case/sources/source_posts.py.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any


def build_source_image_url(
    source_id: int | None, filename: str | None, updated_at: datetime | None
) -> str | None:
    if not filename or source_id is None:
        return None
    # ?v=<ts> — cache-busting: имя файла при перезаливке не меняется (source_id.ext),
    # без версии в URL браузер мог бы продолжать отдавать из кэша старую картинку.
    v = int(updated_at.timestamp()) if updated_at else 0
    return f"/api/v1/sources/{source_id}/image?v={v}"


def extract_post_own_image_url(attachments: Any) -> str | None:
    """
    Картинка из самого поста, если она там есть. Сейчас реально работает только
    для VK (attachments: [{"type": "photo", "url": "https://..."}], см.
    infrastructure/vk/normalizer.py). RSS вложения вообще не собирает
    (persist.py:persist_rss_public_for_source), а Telegram кладёт в
    payload.media_urls плейсхолдеры вида "tg://photo/<id>" — не настоящие
    HTTP-ссылки, поэтому картинкой они не считаются (иначе <img src> будет
    битым). Соответственно у RSS и Telegram постов сейчас всегда сработает
    fallback на картинку источника.
    """
    if not isinstance(attachments, list):
        return None
    for att in attachments:
        if isinstance(att, dict) and att.get("type") == "photo" and att.get("url"):
            return att["url"]
    return None
