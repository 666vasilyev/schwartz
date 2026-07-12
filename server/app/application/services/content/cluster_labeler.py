"""
LLM-разметка сюжетных кластеров: заголовок, краткое содержание, динамические темы.

Динамические темы: модель сама подбирает 1–4 коротких ярлыка для сюжета
(а не выбирает из фиксированного списка). Так покрываем редкие темы и не
поддерживаем таксономию вручную.

Запускается отдельно от инкрементальной кластеризации: после того как кластер
"созрел" (например, ≥ N постов) или давно не обновлялся.
"""
from __future__ import annotations

import asyncio
from collections.abc import Sequence

from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.clients.llm import ask_llm_json
from app.infrastructure.db.orm.models import StoryCluster
from app.infrastructure.db.orm.session import AsyncSessionLocal
from app.infrastructure.repositories import (
    get_cluster_by_id,
    list_cluster_post_texts,
    update_cluster_labels,
)
from app.utils.logger import get_logger

logger = get_logger(__name__)

_MAX_CHARS_PER_POST = 800
_MAX_POSTS_FOR_LABELING = 5
# Верхняя граница одновременных LLM/DB-вызовов при lazy-доразметке трендов —
# защищает пул соединений (pool_size=10 + max_overflow=20) и LLM-провайдера
# от всплеска, когда в выдаче сразу много неразмеченных кластеров.
_LAZY_LABELING_CONCURRENCY = 8

_SYSTEM = (
    "Ты помощник новостного редактора. На вход — несколько постов СМИ "
    "об одном событии. Сформулируй:\n"
    "  • title: короткий нейтральный заголовок сюжета (до 100 символов);\n"
    "  • summary: фактическое описание сюжета в 1–3 предложениях;\n"
    "  • topics: массив 1–4 коротких ярлыков (1–2 слова каждый), "
    "отражающих темы (например: \"политика\", \"энергетика\", \"конфликт\").\n"
    "Отвечай только валидным JSON в формате "
    "{\"title\": str, \"summary\": str, \"topics\": [str]}."
)


def _build_prompt(post_texts: list[str]) -> str:
    blocks = []
    for i, t in enumerate(post_texts, 1):
        t = (t or "").strip()
        if not t:
            continue
        blocks.append(f"[Пост {i}]\n{t[:_MAX_CHARS_PER_POST]}")
    return "\n\n".join(blocks)


async def label_cluster(db: AsyncSession, cluster_id: int) -> bool:
    """
    Сгенерировать/обновить title, summary, topics для одного кластера.
    Возвращает True при успехе.
    """
    cluster = await get_cluster_by_id(db, cluster_id)
    if cluster is None:
        return False

    texts = await list_cluster_post_texts(
        db, cluster_id, limit=_MAX_POSTS_FOR_LABELING
    )
    if not texts:
        return False

    prompt = _build_prompt(texts)
    try:
        result = await ask_llm_json(prompt, system=_SYSTEM, max_tokens=400)
    except Exception as exc:
        logger.warning(
            "cluster_labeling_failed",
            cluster_id=cluster_id,
            error=str(exc),
        )
        return False

    title = str(result.get("title", "") or "").strip()[:512] or None
    summary = str(result.get("summary", "") or "").strip() or None
    raw_topics = result.get("topics") or []
    topics: list[str] = []
    if isinstance(raw_topics, list):
        for t in raw_topics:
            if not isinstance(t, str):
                continue
            t_clean = t.strip().lower()[:64]
            if t_clean and t_clean not in topics:
                topics.append(t_clean)
            if len(topics) >= 4:
                break

    await update_cluster_labels(
        db,
        cluster_id=cluster_id,
        title=title,
        summary=summary,
        topics=topics or None,
    )

    logger.info(
        "cluster_labeled",
        cluster_id=cluster_id,
        title=title,
        topics=topics,
    )
    return True


async def _label_cluster_isolated(cluster_id: int) -> bool:
    """
    Разметка одного кластера в собственной сессии/транзакции — нужна, чтобы
    несколько кластеров можно было размечать конкурентно (asyncio.gather):
    AsyncSession не потокобезопасна для параллельных операций на одном объекте.
    """
    async with AsyncSessionLocal() as session:
        try:
            ok = await label_cluster(session, cluster_id)
            await session.commit()
            return ok
        except Exception as exc:
            await session.rollback()
            logger.warning(
                "cluster_labeling_isolated_failed",
                cluster_id=cluster_id,
                error=str(exc),
            )
            return False


async def ensure_labels_for_clusters(cluster_ids: Sequence[int]) -> None:
    """
    Лениво доразмечает через LLM переданные кластеры, параллельно (с ограничением
    concurrency), каждый — в своей сессии. Ошибки отдельных кластеров не прерывают
    остальные (см. _label_cluster_isolated — сам гасит исключения).
    """
    ids = list(dict.fromkeys(int(cid) for cid in cluster_ids))  # dedupe, сохраняем порядок
    if not ids:
        return

    semaphore = asyncio.Semaphore(_LAZY_LABELING_CONCURRENCY)

    async def _bounded(cid: int) -> None:
        async with semaphore:
            await _label_cluster_isolated(cid)

    await asyncio.gather(*(_bounded(cid) for cid in ids))


async def label_missing_in_rows(
    db: AsyncSession,
    rows: Sequence[tuple[StoryCluster, int, int]],
) -> None:
    """
    Хелпер для trending-эндпоинтов: находит среди строк (cluster, posts_in_window,
    sources_in_window) кластеры без title, доразмечает их конкурентно в изолированных
    сессиях, затем обновляет переданные ORM-объекты в сессии текущего запроса
    (db.refresh), чтобы в ответ ушли свежие title/summary/topics.
    """
    unlabeled = [cluster for cluster, _, _ in rows if cluster.title is None]
    if not unlabeled:
        return
    await ensure_labels_for_clusters([int(c.id) for c in unlabeled])
    for cluster in unlabeled:
        await db.refresh(cluster)
