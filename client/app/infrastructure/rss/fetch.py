"""
Скачивание тела ленты по URL: редиректы, лимит размера, таймаут.
"""
from __future__ import annotations

import httpx

from app.utils.logger import get_logger

logger = get_logger(__name__)

_DEFAULT_UA = "news-analyzer-collector/0.1 (+https://github.com/)"
_MAX_BYTES = 10 * 1024 * 1024


async def fetch_feed_bytes(
    url: str,
    *,
    timeout: float = 45.0,
    max_bytes: int = _MAX_BYTES,
) -> tuple[bytes, str | None]:
    """
    GET ленты. Возвращает (тело ответа, финальный Content-Type или None).
    """
    headers = {"User-Agent": _DEFAULT_UA, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*"}
    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        headers=headers,
    ) as client:
        async with client.stream("GET", url) as resp:
            resp.raise_for_status()
            ctype = resp.headers.get("content-type")
            chunks: list[bytes] = []
            total = 0
            async for chunk in resp.aiter_bytes():
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    logger.warning("rss_fetch_truncated_max_bytes", url=url, max_bytes=max_bytes)
                    raise ValueError(f"Ответ ленты больше {max_bytes} байт")
                chunks.append(chunk)
            body = b"".join(chunks)
            logger.info("rss_fetch_ok", url=url, bytes=len(body), content_type=ctype)
            return body, ctype
