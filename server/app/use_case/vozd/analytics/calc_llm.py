"""LLM-метрики («гипотеза модели», не факт): считаются по выборке, результат кэшируется в БД."""
from __future__ import annotations

import asyncio
from collections import Counter
from datetime import timedelta
from typing import Any

from app.infrastructure.clients.llm import ask_llm_json
from app.infrastructure.prompts import load_prompt
from app.use_case.vozd.analytics import calc_general as gen
from app.use_case.vozd.analytics import util as u
from app.use_case.vozd.analytics.context import AnalyticsContext, utcnow
from app.use_case.vozd.analytics.registry import InsufficientData, calculator

_CHUNK_CHARS = 5500
_MAX_CHUNKS = 8
_CONCURRENCY = 3
MOTIVE_KEYS = ("social_belonging", "self_realization", "informational", "entertainment", "protest")


async def sample_texts(ctx: AnalyticsContext) -> list[str]:
    """Выборка текстов для LLM: топ постов по вовлечённости + комментарии последних M дней."""
    posts = sorted([p for p in await ctx.posts() if p.text.strip()], key=lambda p: -p.engagement)
    out = [p.text.strip()[:800] for p in posts[: max(ctx.sample_size // 2, 1)]]
    comments = [c for c in await ctx.comments() if c.text.strip()]
    recent_from = utcnow() - timedelta(days=ctx.sample_recent_days)
    recent = [c for c in comments if c.published_at and c.published_at >= recent_from]
    pool = recent if recent else sorted(comments, key=lambda c: -len(c.text))
    out += [c.text.strip()[:500] for c in pool[: ctx.sample_size]]
    return out


def chunks(texts: list[str]) -> list[str]:
    res, cur, size = [], [], 0
    for t in texts:
        if size + len(t) > _CHUNK_CHARS and cur:
            res.append("\n---\n".join(cur))
            cur, size = [], 0
        cur.append(t)
        size += len(t) + 5
    if cur:
        res.append("\n---\n".join(cur))
    return res[:_MAX_CHUNKS]


async def _gather(coros):
    sem = asyncio.Semaphore(_CONCURRENCY)

    async def run(c):
        async with sem:
            return await c

    return await asyncio.gather(*(run(c) for c in coros))


def _finish(ctx: AnalyticsContext, value: Any, at, cached: bool) -> Any:
    ctx.meta = {"computed_at": at.isoformat(), "from_cache": cached}
    return value


@calculator("II.28", llm=True, note="оценка ценностей по выборке текстов (шкала Шварца), гипотеза модели")
async def schwartz(ctx: AnalyticsContext):
    from app.application.services.content.schwartz_values import extract_schwartz_values_from_text

    async def factory():
        texts = await sample_texts(ctx)
        if not texts:
            raise InsufficientData("нет текстов для оценки")
        parts = chunks(texts)
        results = await _gather(
            extract_schwartz_values_from_text(p, provider=ctx.provider, model=ctx.model) for p in parts
        )
        results = [r for r in results if r]
        keys = results[0].keys()
        avg = {k: u.r4(sum(r[k] for r in results) / len(results)) for k in keys}
        total = sum(avg.values()) or 1
        return {
            "values": {k: u.r4(v / total) for k, v in avg.items()},
            "dominant": max(avg, key=avg.get),
            "texts_used": len(texts),
            "llm_calls": len(parts),
            "quality": "llm_hypothesis",
        }

    return _finish(ctx, *await ctx.cached("schwartz", factory))


@calculator("III.14", llm=True, note="лексикон по всему корпусу + LLM-оценка деструктивности по выборке")
async def tonality(ctx: AnalyticsContext):
    from app.application.services.content.text import analyze_text

    await ctx.prepare()
    rows = [r for r in [*await ctx.posts(), *await ctx.comments()] if r.text.strip()]
    if not rows:
        raise InsufficientData("нет текстов")
    pos = sum(1 for r in rows if r.f.score > 0)
    neg = sum(1 for r in rows if r.f.score < 0)
    value: dict[str, Any] = {
        "lexicon": {
            "messages": len(rows),
            "positive_share": u.share(pos, len(rows)),
            "negative_share": u.share(neg, len(rows)),
            "neutral_share": u.share(len(rows) - pos - neg, len(rows)),
            "mean_tone": u.mean([r.f.score for r in rows if (r.f.pos + r.f.neg) > 0]),
        },
        "llm": None,
    }

    async def factory():
        parts = chunks(await sample_texts(ctx))
        if not parts:
            raise InsufficientData("нет текстов для оценки")
        res = await _gather(analyze_text(p, provider=ctx.provider, model=ctx.model) for p in parts)
        scores = [s for s, _ in res]
        return {
            "destructiveness_mean": u.mean(scores),
            "destructiveness_max": u.r4(max(scores)),
            "reasons": [r for _, r in res if r][:3],
            "llm_calls": len(parts),
            "quality": "llm_hypothesis",
        }

    try:
        llm, at, cached = await ctx.cached("tonality", factory)
        value["llm"] = llm
        ctx.meta = {"computed_at": at.isoformat(), "from_cache": cached}
    except InsufficientData:
        raise
    except Exception as exc:  # noqa: BLE001 — LLM недоступен: лексическая часть всё равно полезна
        value["llm_error"] = str(getattr(exc, "detail", exc))[:300]
    return value


@calculator("I.27", llm=True, note="краткое содержание описаний группы и источников — заявленные цели")
async def declared_goals(ctx: AnalyticsContext):
    from app.application.services.content.llm_summarizer import summarize_post_texts

    async def factory():
        texts = [t for t in [ctx.group.description, *[s.description for s in ctx.sources]] if t and len(t.strip()) >= 20]
        if not texts:
            raise InsufficientData("у группы и источников нет описаний")
        title, summary, topics = await summarize_post_texts(texts, provider=ctx.provider, model=ctx.model)
        return {"title": title, "summary": summary, "topics": topics, "texts_used": len(texts), "quality": "llm_hypothesis"}

    return _finish(ctx, *await ctx.cached("goals", factory))


@calculator("III.5", llm=True, note="топ постов по вовлечённости + краткое содержание")
async def popular_posts(ctx: AnalyticsContext):
    from app.application.services.content.llm_summarizer import summarize_post_texts

    posts = sorted([p for p in await ctx.posts() if p.text.strip()], key=lambda p: -p.engagement)[:10]
    if not posts:
        raise InsufficientData("нет постов с текстом")
    value = {
        "top_posts": [
            {"post_id": p.id, "url": p.url, "engagement": p.engagement, "likes": p.likes, "comments": p.comments_count,
             "reposts": p.reposts, "snippet": p.text[:200]}
            for p in posts
        ],
        "summary": None,
    }

    async def factory():
        title, summary, topics = await summarize_post_texts(
            [p.text for p in posts], provider=ctx.provider, model=ctx.model
        )
        return {"title": title, "summary": summary, "topics": topics, "quality": "llm_hypothesis"}

    try:
        value["summary"], at, cached = await ctx.cached("popular", factory)
        ctx.meta = {"computed_at": at.isoformat(), "from_cache": cached}
    except Exception as exc:  # noqa: BLE001
        value["llm_error"] = str(getattr(exc, "detail", exc))[:300]
    return value


async def _motives(ctx: AnalyticsContext) -> dict[str, Any]:
    async def factory():
        texts = await sample_texts(ctx)
        parts = chunks([t for t in texts])
        if not parts:
            raise InsufficientData("нет текстов для оценки")
        system = load_prompt("participation_motives_system")

        async def one(chunk: str):
            return await ask_llm_json(f"Сообщения:\n\n{chunk}", system=system, provider=ctx.provider, model=ctx.model, max_tokens=300)

        res = await _gather(one(p) for p in parts)
        dist: dict[str, float] = {}
        for k in MOTIVE_KEYS:
            vals = []
            for r in res:
                try:
                    vals.append(max(0.0, min(1.0, float((r or {}).get(k, 0.0)))))
                except (TypeError, ValueError, AttributeError):
                    vals.append(0.0)
            dist[k] = u.r4(sum(vals) / len(vals))
        return {"distribution": dist, "texts_used": len(texts), "llm_calls": len(parts), "quality": "llm_hypothesis"}

    value, at, cached = await ctx.cached("motives", factory)
    ctx.meta = {"computed_at": at.isoformat(), "from_cache": cached}
    return value


_MOTIVE_BY_ID = {
    "II.9": "social_belonging",
    "II.10": "self_realization",
    "II.11": "informational",
    "II.12": "entertainment",
    "II.13": "protest",
}


@calculator("II.9", "II.10", "II.11", "II.12", "II.13", llm=True, note="мотивы участия по выборке (один LLM-расчёт на все пять)")
async def motives(ctx: AnalyticsContext):
    value = await _motives(ctx)
    key = _MOTIVE_BY_ID[ctx.metric_id]
    return {"motive": key, "score": value["distribution"][key], **value}


async def _conflicts(ctx: AnalyticsContext) -> dict[str, Any]:
    async def factory():
        detected = await gen.conflict_threads(ctx)
        cands = detected["top"][:8]
        if not cands:
            raise InsufficientData("конфликтных обсуждений не найдено")
        by_post: dict[int, list] = {}
        for c in await ctx.comments():
            by_post.setdefault(c.post_id, []).append(c)
        posts = {p.id: p for p in await ctx.posts()}
        system = load_prompt("conflict_classification_system")

        async def one(cand):
            p = posts.get(cand["post_id"])
            body = (p.text[:600] if p and p.text else "") + "\n\nКомментарии:\n"
            body += "\n".join("- " + c.text.strip()[:250] for c in by_post.get(cand["post_id"], [])[:15])
            r = await ask_llm_json(body[:3500], system=system, provider=ctx.provider, model=ctx.model, max_tokens=300)
            return cand, r if isinstance(r, dict) else {}

        res = await _gather(one(c) for c in cands)
        items, types = [], Counter()
        for cand, r in res:
            if not r.get("is_conflict", True):
                continue
            t = str(r.get("type") or "other")
            types[t] += 1
            items.append(
                {
                    "post_id": cand["post_id"],
                    "url": cand["url"],
                    "type": t,
                    "cause": str(r.get("cause") or "")[:200],
                    "intensity": r.get("intensity"),
                    "conflict_score": cand["conflict_score"],
                }
            )
        return {
            "classified": len(items),
            "types": u.top(types, 10, "type"),
            "items": items,
            "quality": "llm_hypothesis",
        }

    value, at, cached = await ctx.cached("conflicts", factory)
    ctx.meta = {"computed_at": at.isoformat(), "from_cache": cached}
    return value


@calculator("II.50", llm=True, note="типы конфликтов в самых «горячих» обсуждениях (LLM)")
async def conflict_types(ctx: AnalyticsContext):
    v = await _conflicts(ctx)
    return {"classified": v["classified"], "types": v["types"], "quality": v["quality"]}


@calculator("II.51", "III.46", llm=True, note="причины конфликтов в самых «горячих» обсуждениях (LLM)")
async def conflict_causes(ctx: AnalyticsContext):
    v = await _conflicts(ctx)
    return {"classified": v["classified"], "items": v["items"], "quality": v["quality"]}
