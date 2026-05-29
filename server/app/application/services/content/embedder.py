"""
Эмбеддинги текстов через sentence-transformers.

Модель загружается лениво при первом обращении (несколько секунд + ~300MB RAM),
после чего используется один экземпляр на процесс. Семейство E5 требует префикс
"passage: " для документов и "query: " для запросов — поэтому два метода.

Кодирование само по себе синхронное и CPU-bound, поэтому оборачиваем в
asyncio.to_thread, чтобы не блокировать event loop FastAPI.
"""
from __future__ import annotations

import asyncio
import hashlib
import threading
from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.utils.logger import get_logger

if TYPE_CHECKING:  # pragma: no cover
    from sentence_transformers import SentenceTransformer

logger = get_logger(__name__)
settings = get_settings()

_model: "SentenceTransformer | None" = None
_model_lock = threading.Lock()


def _get_model() -> "SentenceTransformer":
    """Singleton-загрузчик модели. Тяжёлый импорт только при первом вызове."""
    global _model
    if _model is not None:
        return _model
    with _model_lock:
        if _model is not None:
            return _model
        from sentence_transformers import SentenceTransformer

        logger.info(
            "embedder_loading",
            model=settings.embedding_model_name,
            dim=settings.embedding_dim,
        )
        _model = SentenceTransformer(settings.embedding_model_name)
        logger.info("embedder_loaded", model=settings.embedding_model_name)
        return _model


def _truncate(text: str) -> str:
    return text.strip()[: settings.embedding_max_chars]


def text_hash(text: str) -> str:
    """Стабильный хэш нормализованного текста — для инвалидации эмбеддинга."""
    return hashlib.sha256(_truncate(text).encode("utf-8")).hexdigest()


def _encode_sync(texts: list[str], *, is_query: bool) -> list[list[float]]:
    model = _get_model()
    prefix = "query: " if is_query else "passage: "
    prepared = [prefix + _truncate(t) for t in texts]
    vectors = model.encode(
        prepared,
        batch_size=settings.embedding_batch_size,
        normalize_embeddings=True,  # L2-нормализация => cosine == dot product
        convert_to_numpy=True,
        show_progress_bar=False,
    )
    return [v.tolist() for v in vectors]


async def encode_passages(texts: list[str]) -> list[list[float]]:
    """Эмбеддинги для постов/документов (длинных текстов)."""
    if not texts:
        return []
    return await asyncio.to_thread(_encode_sync, texts, is_query=False)


async def encode_query(text: str) -> list[float]:
    """Эмбеддинг для запроса (короткой строки)."""
    vectors = await asyncio.to_thread(_encode_sync, [text], is_query=True)
    return vectors[0]


def model_name() -> str:
    return settings.embedding_model_name
