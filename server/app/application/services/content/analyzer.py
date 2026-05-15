"""
Content Analysis Orchestrator.

LLM: оценка деструктивности текста + ценности Шварца (JSON с числами).
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass

from app.application.services.content.schwartz_values import (
    SCHWARTZ_KEYS,
    extract_schwartz_values_from_text,
    merge_details_with_schwartz,
    normalize_schwartz_payload,
)
from app.application.services.content.text import analyze_text
from app.core.config import get_settings
from app.infrastructure.db.orm.models import Post
from app.presentation.schemas.analysis import ContentAnalysisResult
from app.presentation.schemas.post import PostInput
from app.utils.logger import get_logger

logger = get_logger(__name__)
settings = get_settings()

# Ограничение параллельных LLM-запросов: каждый analyze_post делает 2 вызова,
# поэтому реальных HTTP-соединений будет _LLM_CONCURRENCY * 2
_LLM_CONCURRENCY = 5
_llm_semaphore = asyncio.Semaphore(_LLM_CONCURRENCY)


async def analyze_post(
    post: PostInput,
    *,
    include_schwartz_values: bool = True,
) -> ContentAnalysisResult:
    """LLM: текст (деструктивность) + 10 измерений Шварца. В БД сохраняются только измерения Шварца (см. роут)."""

    async def _schwartz_or_none():
        if not include_schwartz_values:
            return None
        return await extract_schwartz_values_from_text(post.text)

    (text_score, text_reason), schwartz_values = await asyncio.gather(
        analyze_text(post.text),
        _schwartz_or_none(),
    )

    destruct_score = text_score

    logger.info(
        "channel_score",
        channel="text",
        score=round(text_score, 4),
        detail=text_reason or "—",
    )
    logger.info(
        "post_analysis_complete",
        destruct_score=round(destruct_score, 4),
        threshold=settings.destruct_threshold,
    )

    details = merge_details_with_schwartz(text_reason, schwartz_values)

    return ContentAnalysisResult(
        destruct_score=destruct_score,
        schwartz_values=schwartz_values,
        text_score=text_score,
        details=details,
    )


def _mean_schwartz(vectors: list[dict[str, float]]) -> dict[str, float]:
    if not vectors:
        return {k: 0.0 for k in SCHWARTZ_KEYS}
    n = len(vectors)
    return {k: sum(v[k] for v in vectors) / n for k in SCHWARTZ_KEYS}


@dataclass
class AnalyzedPostSnapshot:
    post_id: int
    vk_post_id: str | None
    analysis: ContentAnalysisResult
    is_destructive: bool


@dataclass
class SourcePostsAnalysisBatch:
    posts: list[AnalyzedPostSnapshot]
    aggregate_schwartz: dict[str, float]
    skipped_empty_text: int


async def analyze_source_posts_in_memory(posts: list[Post]) -> SourcePostsAnalysisBatch:
    """
    Для каждого поста с непустым текстом — отдельный вызов LLM (как analyze_post).
    Все такие вызовы запускаются параллельно через asyncio.gather.
    Показатели по постам только в памяти; агрегат Шварца сохраняет вызывающий код в БД.
    По паблику: среднее по каждому ключу Шварца по всем таким постам.
    """
    to_analyze: list[Post] = []
    skipped_empty = 0
    for row in posts:
        if not row.text or not str(row.text).strip():
            skipped_empty += 1
        else:
            to_analyze.append(row)

    async def _analyze_with_limit(row: Post) -> ContentAnalysisResult:
        async with _llm_semaphore:
            return await analyze_post(
                PostInput(
                    vk_post_id=row.vk_post_id,
                    owner_id=row.owner_id,
                    text=row.text,
                )
            )

    analyses: list[ContentAnalysisResult] = (
        list(await asyncio.gather(*[_analyze_with_limit(row) for row in to_analyze]))
        if to_analyze
        else []
    )

    snapshots: list[AnalyzedPostSnapshot] = []
    schwartz_vectors: list[dict[str, float]] = []
    for row, analysis in zip(to_analyze, analyses, strict=True):
        sv = analysis.schwartz_values
        if isinstance(sv, dict):
            schwartz_vectors.append(normalize_schwartz_payload(sv))
        else:
            schwartz_vectors.append({k: 0.0 for k in SCHWARTZ_KEYS})

        destructive = analysis.destruct_score >= settings.destruct_threshold
        snapshots.append(
            AnalyzedPostSnapshot(
                post_id=int(row.id),
                vk_post_id=row.vk_post_id,
                analysis=analysis,
                is_destructive=destructive,
            )
        )

    aggregate = _mean_schwartz(schwartz_vectors)
    logger.info(
        "source_posts_analyzed_in_memory",
        n_posts=len(snapshots),
        skipped_empty=skipped_empty,
    )
    return SourcePostsAnalysisBatch(
        posts=snapshots,
        aggregate_schwartz=aggregate,
        skipped_empty_text=skipped_empty,
    )
