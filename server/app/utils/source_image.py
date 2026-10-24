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
    """
    Отдаётся как статика через nginx (см. nginx.conf: location ^~ /media/),
    в обход бэкенда и его JWT-авторизации — раньше URL указывал на
    GET /api/v1/sources/{id}/image, но этот эндпоинт защищён общей
    авторизацией роутера sources, а браузер не может приложить
    Authorization-заголовок к обычному <img src>. Картинки источников не
    секретные, поэтому раздаём их как публичную статику напрямую с диска
    (media_uploads volume, примонтированный в nginx как /var/www/media).
    """
    if not filename or source_id is None:
        return None
    # ?v=<ts> — cache-busting: имя файла при перезаливке не меняется (source_id.ext),
    # а nginx кэширует такие URL агрессивно и надолго (immutable) — поэтому
    # версия обязана быть частью самого URL, иначе браузер продолжит отдавать
    # старую картинку из кэша после перезаливки.
    v = int(updated_at.timestamp()) if updated_at else 0
    return f"/media/sources/{filename}?v={v}"


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
