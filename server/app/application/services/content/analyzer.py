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

_LLM_CONCURRENCY = 5
_llm_semaphore = asyncio.Semaphore(_LLM_CONCURRENCY)


async def analyze_post(
    post: PostInput,
    *,
    include_schwartz_values: bool = True,
    provider: str | None = None,
    model: str | None = None,
    post_index: int | None = None,
    posts_total: int | None = None,
) -> ContentAnalysisResult:
    """LLM: текст (деструктивность) + 10 измерений Шварца."""
    prefix = f"[{post_index}/{posts_total}] " if post_index is not None else ""
    text_preview = (post.text or "")[:80].replace("\n", " ")
    logger.info(
        "post_llm_start",
        index=post_index,
        total=posts_total,
        text_preview=text_preview,
    )

    async def _schwartz_or_none():
        if not include_schwartz_values:
            return None
        return await extract_schwartz_values_from_text(post.text, provider=provider, model=model)

    (text_score, text_reason), schwartz_values = await asyncio.gather(
        analyze_text(post.text, provider=provider, model=model),
        _schwartz_or_none(),
    )

    destruct_score = text_score
    is_destructive = destruct_score >= settings.destruct_threshold

    logger.info(
        "post_llm_done",
        index=post_index,
        total=posts_total,
        destruct_score=round(destruct_score, 4),
        is_destructive=is_destructive,
        reason=text_reason or "—",
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


async def analyze_source_posts_in_memory(
    posts: list[Post],
    *,
    provider: str | None = None,
    model: str | None = None,
) -> SourcePostsAnalysisBatch:
    to_analyze: list[Post] = []
    skipped_empty = 0
    for row in posts:
        if not row.text or not str(row.text).strip():
            skipped_empty += 1
        else:
            to_analyze.append(row)

    n_total = len(to_analyze)
    logger.info(
        "batch_llm_start",
        posts_to_analyze=n_total,
        posts_skipped_empty=skipped_empty,
        provider=provider,
        model=model,
        concurrency=_LLM_CONCURRENCY,
    )

    completed = 0

    async def _analyze_with_limit(row: Post, index: int) -> ContentAnalysisResult:
        nonlocal completed
        async with _llm_semaphore:
            result = await analyze_post(
                PostInput(
                    vk_post_id=row.vk_post_id,
                    owner_id=row.owner_id,
                    text=row.text,
                ),
                provider=provider,
                model=model,
                post_index=index,
                posts_total=n_total,
            )
            completed += 1
            logger.info("batch_llm_progress", done=completed, total=n_total)
            return result

    analyses: list[ContentAnalysisResult] = (
        list(await asyncio.gather(*[_analyze_with_limit(row, i + 1) for i, row in enumerate(to_analyze)]))
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
        "batch_llm_done",
        posts_analyzed=len(snapshots),
        posts_skipped_empty=skipped_empty,
    )
    return SourcePostsAnalysisBatch(
        posts=snapshots,
        aggregate_schwartz=aggregate,
        skipped_empty_text=skipped_empty,
    )
