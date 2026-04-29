"""
Разбор ссылок на сообщества/страницы VK: short name, club/public/id.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse


def normalize_vk_url(url: str) -> str:
    s = url.strip()
    if not s.lower().startswith("http"):
        s = "https://" + s
    p = urlparse(s)
    host = (p.netloc or p.path.split("/")[0] or "").lower()
    if "vk.com" not in host and "vk.ru" not in host:
        raise ValueError("Ожидается ссылка на vk.com или vk.ru")
    path = (p.path or "/").strip("/")
    if not path:
        raise ValueError("В ссылке нет пути к паблику (например vk.com/durov)")
    first = path.split("/")[0]
    if not first:
        raise ValueError("Пустой идентификатор паблика")
    return f"https://vk.com/{first}"


def public_path_segment_from_url(url: str) -> str:
    """Первый сегмент пути после нормализации (например `durov` из https://vk.com/durov)."""
    n = normalize_vk_url(url)
    p = urlparse(n)
    seg = p.path.strip("/").split("/")[0] if p.path else ""
    if not seg:
        raise ValueError("В ссылке нет пути к паблику")
    return seg


def extract_screen_or_id_token(path_segment: str) -> tuple[str, int | None]:
    s = path_segment.strip()
    m = re.match(r"^club(\d+)$", s, re.I)
    if m:
        gid = int(m.group(1))
        return s, -gid
    m = re.match(r"^public(\d+)$", s, re.I)
    if m:
        gid = int(m.group(1))
        return s, -gid
    m = re.match(r"^id(\d+)$", s, re.I)
    if m:
        uid = int(m.group(1))
        return s, uid
    return s, None
