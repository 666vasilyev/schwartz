"""
Общая подготовка данных для отчёта по выборке постов (саммари + ЦКМ-аналитика) —
используется обоими рендерерами (report_docx.py, report_pdf.py), см.
use_case/posts/summary_report.py (POST /api/v1/posts/summary/report).

Саммари — тот же LLM-вызов, что и в обычном POST /api/v1/posts/summary (см.
llm_summarizer.summarize_post_texts — переиспользуется как есть, не
дублируется). ЦКМ-аналитика — словарный метод (score_text), тот же, что уже
используется в /analyze/lemma/* ручках: считается по каждому посту отдельно
и агрегируется (среднее + нормировка), см. _lemma_aggregate.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone

from app.application.services.content.lemma_scorer import CSV_COLUMNS, LemmaLang, score_text
from app.application.services.content.llm_summarizer import summarize_post_texts
from app.infrastructure.db.orm.models import Post
from app.use_case.analyze._lemma_aggregate import aggregate_categories, aggregate_vectors
from app.use_case.posts.get_all import _build_post_url

_TEXT_SNIPPET_LEN = 200


@dataclass
class PostReportItem:
    id: int
    source_name: str | None
    source_type: str | None
    published_at: datetime | None
    url: str | None
    text_snippet: str
    has_text: bool


@dataclass
class PostReportData:
    title: str | None
    summary: str | None
    topics: list[str]
    generated_at: datetime
    lang: LemmaLang
    posts_requested: int
    posts_used: int  # сколько реально попало и в саммари, и в ЦКМ (непустой текст)
    missing_post_ids: list[int]
    schwartz: dict[str, float] = field(default_factory=dict)
    categories: dict[str, float] = field(default_factory=dict)
    posts: list[PostReportItem] = field(default_factory=list)


async def build_post_report_data(
    rows: list[tuple[Post, str | None, str | None, str | None]],
    *,
    lang: LemmaLang,
    posts_requested: int,
    missing_post_ids: list[int],
    preset_title: str | None = None,
    preset_summary: str | None = None,
    preset_topics: list[str] | None = None,
) -> PostReportData:
    """
    rows — (Post, source_type, source_name, source_url), в порядке выбора пользователя.

    preset_summary (и title/topics вместе с ним) — саммари, уже показанное
    пользователю на экране (см. POST /api/v1/posts/summary): если передано,
    LLM повторно НЕ вызывается, отчёт использует этот текст как есть — иначе
    саммари в отчёте могло бы отличаться от того, что человек уже видел
    (LLM не детерминирована) или отредактировал сам. ЦКМ-аналитика всегда
    считается заново по текущим текстам постов — она не зависит от LLM и
    проблемы рассинхронизации для неё нет.
    """
    posts_meta: list[PostReportItem] = []
    texts: list[str] = []

    for post, source_type, source_name, source_url in rows:
        text = (post.text or "").strip()
        snippet = text[:_TEXT_SNIPPET_LEN] + "…" if len(text) > _TEXT_SNIPPET_LEN else text
        posts_meta.append(
            PostReportItem(
                id=post.id,
                source_name=source_name,
                source_type=source_type,
                published_at=post.published_at,
                url=_build_post_url(post, source_type, source_url),
                text_snippet=snippet,
                has_text=bool(text),
            )
        )
        if text:
            texts.append(text)

    if preset_summary:
        title, summary, topics = preset_title, preset_summary, list(preset_topics or [])
    elif texts:
        title, summary, topics = await summarize_post_texts(texts)
    else:
        title, summary, topics = None, None, []

    schwartz: dict[str, float] = {k: 0.0 for k in CSV_COLUMNS}
    categories: dict[str, float] = {}
    if texts:
        vectors = []
        cat_freqs = []
        for text in texts:
            totals, _matched, cat_freq = score_text(text, lang)
            vectors.append(totals)
            cat_freqs.append(cat_freq)
        schwartz = aggregate_vectors(vectors)
        categories = aggregate_categories(cat_freqs)

    return PostReportData(
        title=title,
        summary=summary,
        topics=topics,
        generated_at=datetime.now(timezone.utc),
        lang=lang,
        posts_requested=posts_requested,
        posts_used=len(texts),
        missing_post_ids=missing_post_ids,
        schwartz=schwartz,
        categories=categories,
        posts=posts_meta,
    )
