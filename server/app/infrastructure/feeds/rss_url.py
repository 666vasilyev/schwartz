"""
Нормализация URL RSS/Atom (без загрузки ленты).
"""
from __future__ import annotations

from urllib.parse import urlparse


def normalize_rss_feed_url(url: str) -> str:
    s = url.strip()
    if not s:
        raise ValueError("Пустой URL ленты")
    if not s.lower().startswith(("http://", "https://")):
        s = "https://" + s
    p = urlparse(s)
    if not p.netloc:
        raise ValueError("В URL ленты нет хоста")
    return s
