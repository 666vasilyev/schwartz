"""Калькуляторы по собранным постам и комментариям: активность, форматы, тексты (A/S-метрики)."""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict
from datetime import datetime
from urllib.parse import urlparse

from sqlalchemy import select

from app.infrastructure.db.orm.models_vozd import VozdMemberSnapshot
from app.use_case.vozd.analytics import lexicons as lx
from app.use_case.vozd.analytics import util as u
from app.use_case.vozd.analytics.context import AnalyticsContext, as_utc
from app.use_case.vozd.analytics.registry import InsufficientData, MetricUnavailable, calculator

_SENT_RE = re.compile(r"[.!?…]+")
_WORD_ONLY = re.compile(r"^[а-яa-z]{3,}$")


def _texts(ctx_rows):
    return [r for r in ctx_rows if r.text and r.text.strip()]


# ── I. численность и активность ─────────────────────────────────────────────


@calculator("I.1")
async def members(ctx: AnalyticsContext):
    total, items = ctx.members_total()
    known = [i for i in items if isinstance(i["members_count"], int)]
    if not known:
        raise MetricUnavailable("в данных источников нет числа участников")
    return {
        "total": total,
        "by_source": items,
        "sources_without_count": len(items) - len(known),
        "note": "сумма по источникам; пересечения аудиторий не вычитаются",
    }


@calculator("I.2")
async def members_dynamics(ctx: AnalyticsContext):
    q = select(VozdMemberSnapshot).where(VozdMemberSnapshot.group_id == ctx.group.id)
    if ctx.window.date_from:
        q = q.where(VozdMemberSnapshot.captured_at >= ctx.window.date_from)
    if ctx.window.date_to:
        q = q.where(VozdMemberSnapshot.captured_at <= ctx.window.date_to)
    snaps = list((await ctx.db.execute(q.order_by(VozdMemberSnapshot.captured_at))).scalars())
    if not snaps:
        raise InsufficientData("снимков численности ещё нет: они записываются после каждого сбора группы")
    last: dict[int, int] = {}
    series: dict[str, int] = {}
    for s in snaps:
        last[s.source_id] = int(s.members_count)
        series[u.day(as_utc(s.captured_at))] = sum(last.values())
    points = [{"date": d, "members": n} for d, n in series.items()]
    if len(points) < 2:
        raise InsufficientData(f"нужно минимум 2 дня наблюдений, сейчас {len(points)}: {points}")
    first, lastp = points[0]["members"], points[-1]["members"]
    pct = u.r4((lastp - first) / first * 100, 2) if first else None
    trend = "stable" if pct is None or abs(pct) < 1 else ("growth" if pct > 0 else "decline")
    return {"series": points, "first": first, "last": lastp, "delta": lastp - first, "delta_pct": pct, "trend": trend}


async def _active_ids(ctx: AnalyticsContext) -> set[tuple[str, int]]:
    ids = {(c.platform, c.from_id) for c in await ctx.human_comments()}
    ids |= {
        (p.platform, p.author_id)
        for p in await ctx.posts()
        if p.author_id and p.author_id > 0 and not ctx.blocked(p.platform, p.author_id)
    }
    return ids


@calculator("I.5", "I.6")
async def active_passive(ctx: AnalyticsContext):
    active = await _active_ids(ctx)
    total, _ = ctx.members_total()
    out = {"active": len(active), "members_total": total or None}
    if total:
        passive = max(total - len(active), 0)
        out.update(
            {
                "passive": passive,
                "active_share": u.share(len(active), total),
                "passive_share": u.share(passive, total),
                "active_to_passive": u.r4(len(active) / passive) if passive else None,
            }
        )
    out["note"] = "активный = автор поста или комментария в окне; пассивные = подписчики − активные"
    return out


@calculator("I.7")
async def activity_types(ctx: AnalyticsContext):
    posts = await ctx.posts()
    authors = {
        (p.platform, p.author_id)
        for p in posts
        if p.author_id and p.author_id > 0 and not ctx.blocked(p.platform, p.author_id)
    }
    commenters = {(c.platform, c.from_id) for c in await ctx.human_comments()}
    total, _ = ctx.members_total()
    return {
        "authors": len(authors),
        "commenters": len(commenters),
        "only_commenters": len(commenters - authors),
        "authors_and_commenters": len(authors & commenters),
        "posts_by_communities": sum(1 for p in posts if not (p.author_id and p.author_id > 0)),
        "observers_estimate": max(total - len(authors | commenters), 0) if total else None,
        "likers": None,
        "note": "лайкеры не собираются (likes.getList не подключён)",
    }


@calculator("I.8", "III.9")
async def time_patterns(ctx: AnalyticsContext):
    matrix = [[0] * 24 for _ in range(7)]
    n = 0
    for r in [*await ctx.posts(), *await ctx.comments()]:
        if r.published_at is not None:
            matrix[r.published_at.weekday()][r.published_at.hour] += 1
            n += 1
    if not n:
        raise InsufficientData("нет сообщений с датой")
    by_hour = [sum(matrix[d][h] for d in range(7)) for h in range(24)]
    by_wd = [sum(row) for row in matrix]
    return {
        "timezone": "UTC",
        "messages": n,
        "matrix_weekday_hour": matrix,
        "weekdays": u.WEEKDAYS,
        "by_hour": by_hour,
        "by_weekday": by_wd,
        "peak_hour": int(max(range(24), key=by_hour.__getitem__)),
        "peak_weekday": u.WEEKDAYS[int(max(range(7), key=by_wd.__getitem__))],
    }


@calculator("III.1")
async def volume(ctx: AnalyticsContext):
    posts, comments = await ctx.posts(), await ctx.comments()
    by_day: dict[str, dict[str, int]] = defaultdict(lambda: {"posts": 0, "comments": 0})
    for p in posts:
        if p.published_at:
            by_day[u.day(p.published_at)]["posts"] += 1
    for c in comments:
        if c.published_at:
            by_day[u.day(c.published_at)]["comments"] += 1
    by_week: dict[str, dict[str, int]] = defaultdict(lambda: {"posts": 0, "comments": 0})
    for d, v in by_day.items():
        wk = u.week(as_utc(datetime.fromisoformat(d)))
        by_week[wk]["posts"] += v["posts"]
        by_week[wk]["comments"] += v["comments"]
    days = max(len(by_day), 1)
    return {
        "posts": len(posts),
        "comments": len(comments),
        "days_with_activity": len(by_day),
        "avg_messages_per_active_day": u.r4((len(posts) + len(comments)) / days),
        "by_day": [{"date": d, **v} for d, v in sorted(by_day.items())],
        "by_week": [{"week": w, **v} for w, v in sorted(by_week.items())],
    }


@calculator("III.2", "I.21")
async def peaks(ctx: AnalyticsContext):
    daily: Counter = Counter()
    for r in [*await ctx.posts(), *await ctx.comments()]:
        if r.published_at:
            daily[u.day(r.published_at)] += 1
    if len(daily) < 3:
        raise InsufficientData("меньше 3 дней с активностью")
    vals = list(daily.values())
    m, sd = sum(vals) / len(vals), u.std(vals) or 0
    peaks_ = [
        {"date": d, "messages": c, "z": u.r4((c - m) / sd) if sd else None}
        for d, c in daily.most_common(10)
        if sd and (c - m) / sd >= 2 and c >= 3
    ]
    return {
        "mean_per_day": u.r4(m),
        "std_per_day": sd,
        "peaks": peaks_,
        "top_days": [{"date": d, "messages": c} for d, c in daily.most_common(5)],
        "note": "пик = день с z ≥ 2; корреляцию с внешними событиями задаёт эксперт (календарь событий не подключён)",
    }


@calculator("III.3")
async def platforms_compare(ctx: AnalyticsContext):
    posts, comments = await ctx.posts(), await ctx.comments()
    out = []
    for platform in sorted({s.source_type or "vk" for s in ctx.sources}):
        pl = "telegram" if platform == "telegram" else "vk"
        members_ = sum(
            (s.source_metadata or {}).get("members_count") or 0 for s in ctx.sources if (s.source_type or "vk") == platform
        )
        pc = [c for c in comments if c.platform == pl]
        participants = {c.from_id for c in pc if c.from_id and c.from_id > 0}
        out.append(
            {
                "platform": pl,
                "sources": sum(1 for s in ctx.sources if (s.source_type or "vk") == platform),
                "members": members_ or None,
                "posts": sum(1 for p in posts if p.platform == pl),
                "comments": len(pc),
                "participants": len(participants),
                "comments_per_1000_members": u.r4(len(pc) / members_ * 1000) if members_ else None,
            }
        )
    return {"platforms": out}


@calculator("III.4", "II.7")
async def reactions(ctx: AnalyticsContext):
    posts = await ctx.posts()
    comments = await ctx.comments()
    n = len(posts)
    out = {
        "posts": n,
        "comments_collected": len(comments),
        "likes": sum(p.likes for p in posts),
        "reposts": sum(p.reposts for p in posts),
        "views": sum(p.views for p in posts),
        "comments_declared": sum(p.comments_count for p in posts),
        "avg_likes_per_post": u.r4(sum(p.likes for p in posts) / n) if n else None,
        "avg_comments_per_post": u.r4(len(comments) / n) if n else None,
        "note": "лайки и просмотры берутся из данных постов; лайки комментариев не собираются",
    }
    return out


def _format_of(attachments: list, has_text: bool) -> list[str]:
    kinds = sorted({str(a.get("type")) for a in attachments if isinstance(a, dict) and a.get("type")})
    if not kinds:
        return ["text_only" if has_text else "empty"]
    return kinds


@calculator("I.19")
async def formats(ctx: AnalyticsContext):
    out = {}
    for name, rows in (("posts", await ctx.posts()), ("comments", await ctx.comments())):
        cnt: Counter = Counter()
        for r in rows:
            for k in _format_of(r.attachments, bool(r.text.strip())):
                cnt[k] += 1
        total = len(rows)
        out[name] = {"total": total, "formats": [{"format": k, "count": c, "share": u.share(c, total)} for k, c in cnt.most_common()]}
    return out


@calculator("III.6")
async def content_vs_engagement(ctx: AnalyticsContext):
    posts = await ctx.posts()
    if len(posts) < 5:
        raise InsufficientData("меньше 5 постов")
    groups: dict[str, list[int]] = defaultdict(list)
    for p in posts:
        for k in _format_of(p.attachments, bool(p.text.strip())):
            groups[k].append(p.engagement)
    return {
        "by_format": sorted(
            (
                {"format": k, "posts": len(v), "avg_engagement": u.r4(sum(v) / len(v)), "avg_likes": None}
                for k, v in groups.items()
            ),
            key=lambda x: -x["avg_engagement"],
        ),
        "engagement": "лайки + репосты + комментарии поста",
    }


@calculator("I.17")
async def platforms(ctx: AnalyticsContext):
    posts, comments = await ctx.posts(), await ctx.comments()
    out = defaultdict(lambda: {"sources": 0, "posts": 0, "comments": 0})
    for s in ctx.sources:
        out["telegram" if s.source_type == "telegram" else "vk"]["sources"] += 1
    for p in posts:
        out[p.platform]["posts"] += 1
    for c in comments:
        out[c.platform]["comments"] += 1
    return {"platforms": [{"platform": k, **v} for k, v in sorted(out.items())]}


@calculator("I.13")
async def naming(ctx: AnalyticsContext):
    await ctx.prepare()
    terms: Counter = Counter()
    tags: Counter = Counter()
    for r in [*await ctx.posts(), *await ctx.comments()]:
        terms.update(w for w in r.f.lemmas if _WORD_ONLY.match(w) and w not in lx.STOPWORDS)
        tags.update(r.f.hashtags)
    return {
        "official_name": ctx.group.name,
        "description": ctx.group.description,
        "sources": [{"name": s.name, "screen_name": s.username, "url": s.url} for s in ctx.sources],
        "hashtags": u.top(tags, 15, "hashtag"),
        "frequent_terms": u.top(terms, 20, "term"),
        "note": "самоназвания и жаргон уточняет эксперт по частым терминам и хэштегам",
    }


@calculator("I.14", "II.8")
async def language(ctx: AnalyticsContext):
    await ctx.prepare()
    cyr = lat = 0
    per: dict[str, list[int]] = defaultdict(lambda: [0, 0])
    for r in [*await ctx.posts(), *await ctx.comments()]:
        cyr += r.f.cyr
        lat += r.f.lat
        per[r.platform][0] += r.f.cyr
        per[r.platform][1] += r.f.lat
    tot = cyr + lat
    if not tot:
        raise InsufficientData("нет текстов")
    ru, en = cyr / tot, lat / tot
    dominant = "ru" if ru >= 0.8 else "en" if en >= 0.8 else "mixed"
    out = {
        "dominant": dominant,
        "shares": {"cyrillic": u.r4(ru), "latin": u.r4(en)},
        "by_platform": {k: {"cyrillic": u.share(v[0], v[0] + v[1]), "latin": u.share(v[1], v[0] + v[1])} for k, v in per.items()},
        "method": "доля кириллицы/латиницы в тексте",
    }
    if ctx.metric_id == "II.8":
        hours = Counter(r.published_at.hour for r in [*await ctx.posts(), *await ctx.comments()] if r.published_at)
        out["activity_by_hour_utc"] = [hours.get(h, 0) for h in range(24)]
        out["note_timezone"] = "часовой пояс профилей не собирается; по часам активности оценивайте пояс косвенно"
    return out


# ── тексты: лексика, стиль, тональность (S) ─────────────────────────────────


@calculator("I.22", "III.50")
async def external_links(ctx: AnalyticsContext):
    await ctx.prepare()
    domains: Counter = Counter()
    msgs = 0
    rows = [*await ctx.posts(), *await ctx.comments()]
    for r in rows:
        if r.f.urls:
            msgs += 1
        for url in r.f.urls:
            host = (urlparse(url if "://" in url else "http://" + url).hostname or "").lower().removeprefix("www.")
            if host:
                domains[host] += 1
    platform_domains = {"vk.com": "vk", "vk.ru": "vk", "m.vk.com": "vk", "t.me": "telegram", "telegram.me": "telegram",
                        "youtube.com": "youtube", "youtu.be": "youtube", "instagram.com": "instagram", "ok.ru": "ok",
                        "wa.me": "whatsapp", "twitter.com": "twitter", "x.com": "twitter"}
    cross: Counter = Counter()
    for d, n in domains.items():
        if d in platform_domains:
            cross[platform_domains[d]] += n
    return {
        "messages_with_links": msgs,
        "share_with_links": u.share(msgs, len(rows)),
        "top_domains": u.top(domains, 25, "domain"),
        "links_to_platforms": u.top(cross, 10, "platform"),
    }


@calculator("III.7")
async def message_length(ctx: AnalyticsContext):
    await ctx.prepare()
    out = {}
    for name, rows in (("posts", await ctx.posts()), ("comments", await ctx.comments())):
        rows = _texts(rows)
        out[name] = {
            "count": len(rows),
            "avg_words": u.mean([r.f.words for r in rows]),
            "avg_chars": u.mean([r.f.chars for r in rows]),
            "median_words": float(sorted(r.f.words for r in rows)[len(rows) // 2]) if rows else None,
        }
    return out


@calculator("III.8")
async def length_vs_engagement(ctx: AnalyticsContext):
    await ctx.prepare()
    posts = _texts(await ctx.posts())
    if len(posts) < 10:
        raise InsufficientData("меньше 10 постов с текстом")
    replies: Counter = Counter(c.parent_id for c in await ctx.comments() if c.parent_id)
    comments = _texts(await ctx.comments())
    return {
        "posts": {
            "n": len(posts),
            "spearman_words_vs_engagement": u.spearman([p.f.words for p in posts], [p.engagement for p in posts]),
        },
        "comments": {
            "n": len(comments),
            "spearman_words_vs_replies": u.spearman([c.f.words for c in comments], [replies.get(c.id, 0) for c in comments]),
        },
        "note": "коэффициент Спирмена: >0 — длиннее ⇒ больше реакций",
    }


@calculator("III.10")
async def seasonality(ctx: AnalyticsContext):
    dates = [r.published_at for r in [*await ctx.posts(), *await ctx.comments()] if r.published_at]
    if not dates:
        raise InsufficientData("нет данных")
    span = (max(dates) - min(dates)).days
    if span < 365:
        raise InsufficientData(f"для сезонности нужно ≥12 месяцев данных, сейчас {span} дн.")
    by_month = Counter(d.month for d in dates)
    return {"span_days": span, "by_month_of_year": [by_month.get(m, 0) for m in range(1, 13)]}


@calculator("III.12", "II.17", "III.13")
async def argumentation(ctx: AnalyticsContext):
    await ctx.prepare()
    rows = _texts(await ctx.comments())
    if not rows:
        raise InsufficientData("нет комментариев")
    with_links = sum(1 for r in rows if r.f.urls)
    causal = sum(1 for r in rows if r.f.causal)
    long_ = sum(1 for r in rows if r.f.words >= 30)
    reasoned = sum(1 for r in rows if r.f.urls or r.f.causal or r.f.words >= 30)
    return {
        "comments": len(rows),
        "share_with_links": u.share(with_links, len(rows)),
        "share_with_causal_markers": u.share(causal, len(rows)),
        "share_long_30plus_words": u.share(long_, len(rows)),
        "reasoned_share": u.share(reasoned, len(rows)),
        "method": "эвристика: ссылка, причинно-следственные связки, развёрнутость; реакцию на фейки оценивает эксперт",
    }


@calculator("III.17")
async def hot_topics(ctx: AnalyticsContext):
    await ctx.prepare()
    cnt: Counter = Counter()
    tone: dict[str, list[float]] = defaultdict(list)
    tags: Counter = Counter()
    for r in [*await ctx.posts(), *await ctx.comments()]:
        words = {w for w in r.f.lemmas if _WORD_ONLY.match(w) and w not in lx.STOPWORDS}
        cnt.update(words)
        tags.update(r.f.hashtags)
        for w in words:
            tone[w].append(abs(r.f.score))
    return {
        "terms": [
            {"term": t, "count": c, "emotional_load": u.mean(tone[t])} for t, c in cnt.most_common(30)
        ],
        "hashtags": u.top(tags, 20, "hashtag"),
        "note": "эмоциональная нагрузка = средняя выраженность тональности в сообщениях с термином",
    }


@calculator("III.29")
async def keywords(ctx: AnalyticsContext):
    await ctx.prepare()
    docs = [
        [w for w in r.f.lemmas if _WORD_ONLY.match(w) and w not in lx.STOPWORDS]
        for r in [*await ctx.posts(), *await ctx.comments()]
    ]
    docs = [d for d in docs if d]
    if len(docs) < 5:
        raise InsufficientData("слишком мало текстов")
    df: Counter = Counter()
    for d in docs:
        df.update(set(d))
    n = len(docs)
    score: Counter = Counter()
    for d in docs:
        tf = Counter(d)
        for w, c in tf.items():
            score[w] += (c / len(d)) * (math.log((n + 1) / (df[w] + 1)) + 1)
    tags: Counter = Counter()
    for r in [*await ctx.posts(), *await ctx.comments()]:
        tags.update(r.f.hashtags)
    return {
        "documents": n,
        "tfidf_top": [{"term": w, "score": u.r4(s, 3), "df": df[w]} for w, s in score.most_common(30)],
        "hashtags": u.top(tags, 20, "hashtag"),
    }


@calculator("II.16")
async def cognitive_activity(ctx: AnalyticsContext):
    await ctx.prepare()
    out = {}
    for name, rows in (("comments", _texts(await ctx.comments())), ("posts", _texts(await ctx.posts()))):
        out[name] = {
            "n": len(rows),
            "question_share": u.share(sum(1 for r in rows if r.f.question), len(rows)),
            "long_30plus_words_share": u.share(sum(1 for r in rows if r.f.words >= 30), len(rows)),
            "avg_words": u.mean([r.f.words for r in rows]),
        }
    return out


@calculator("II.19")
async def readability(ctx: AnalyticsContext):
    out = {}
    for name, rows in (("comments", _texts(await ctx.comments())), ("posts", _texts(await ctx.posts()))):
        words = sents = syl = letters = 0
        for r in rows:
            ws = re.findall(r"[а-яёa-z]+", r.text.lower())
            words += len(ws)
            sents += max(len([s for s in _SENT_RE.split(r.text) if s.strip()]), 1)
            syl += sum(u.syllables(w) for w in ws)
            letters += sum(len(w) for w in ws)
        if not words:
            out[name] = None
            continue
        asl, asw = words / sents, syl / words
        out[name] = {
            "avg_sentence_words": u.r4(asl, 2),
            "avg_syllables_per_word": u.r4(asw, 2),
            "avg_word_length": u.r4(letters / words, 2),
            "flesch_ru": u.r4(206.835 - 1.3 * asl - 60.1 * asw, 1),
        }
    out["note"] = "индекс Флеша в адаптации Обородовой для русского: выше — проще текст"
    return out


@calculator("II.20")
async def emotional_reactivity(ctx: AnalyticsContext):
    await ctx.prepare()
    rows = _texts(await ctx.comments())
    if not rows:
        raise InsufficientData("нет комментариев")
    emo: Counter = Counter()
    for r in rows:
        emo.update(r.f.emotions)
    emotional = sum(1 for r in rows if (r.f.pos + r.f.neg) > 0)
    return {
        "comments": len(rows),
        "emotional_share": u.share(emotional, len(rows)),
        "avg_abs_tone": u.mean([abs(r.f.score) for r in rows]),
        "emotions": {k: emo.get(k, 0) for k in lx.EMOTIONS},
        "method": "лексикон (по всем комментариям); LLM-уточнение по выборке доступно в III.14",
    }


def _daily_scores(rows) -> dict[str, list[float]]:
    d: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if r.published_at and (r.f.pos + r.f.neg) > 0:
            d[u.day(r.published_at)].append(r.f.score)
    return d


@calculator("II.21")
async def emotional_stability(ctx: AnalyticsContext):
    await ctx.prepare()
    rows = _texts(await ctx.comments())
    daily = {d: sum(v) / len(v) for d, v in _daily_scores(rows).items() if len(v) >= 3}
    if len(daily) < 5:
        raise InsufficientData("нужно ≥5 дней с ≥3 эмоциональными комментариями")
    aggr = sum(r.f.aggression for r in rows)
    comp = sum(r.f.compromise for r in rows)
    return {
        "days": len(daily),
        "tone_std_between_days": u.std(list(daily.values())),
        "tone_mean": u.mean(list(daily.values())),
        "aggression_words": aggr,
        "compromise_words": comp,
        "aggression_to_compromise": u.r4(aggr / comp) if comp else None,
    }


@calculator("II.22")
async def group_attachment(ctx: AnalyticsContext):
    await ctx.prepare()
    rows = _texts(await ctx.comments())
    if not rows:
        raise InsufficientData("нет комментариев")
    we = sum(r.f.we for r in rows)
    words = sum(r.f.words for r in rows)
    return {
        "comments_with_we_share": u.share(sum(1 for r in rows if r.f.we), len(rows)),
        "we_per_100_words": u.r4(we / words * 100) if words else None,
    }


@calculator("II.23", "III.25")
async def emoji_markers(ctx: AnalyticsContext):
    await ctx.prepare()
    out = {}
    for name, rows in (("comments", _texts(await ctx.comments())), ("posts", _texts(await ctx.posts()))):
        emo: Counter = Counter()
        for r in rows:
            emo.update(r.f.emojis)
        out[name] = {
            "n": len(rows),
            "share_with_emoji": u.share(sum(1 for r in rows if r.f.emojis), len(rows)),
            "emoji_per_message": u.mean([len(r.f.emojis) for r in rows]),
            "share_with_exclamation": u.share(sum(1 for r in rows if r.f.exclam), len(rows)),
            "top_emoji": u.top(emo, 15, "emoji"),
        }
    return out


@calculator("III.26")
async def emoji_vs_engagement(ctx: AnalyticsContext):
    await ctx.prepare()
    posts = _texts(await ctx.posts())
    if len(posts) < 10:
        raise InsufficientData("меньше 10 постов")
    return {
        "n": len(posts),
        "spearman_emoji_count_vs_engagement": u.spearman([len(p.f.emojis) for p in posts], [p.engagement for p in posts]),
    }


@calculator("III.15", "III.19")
async def triggers(ctx: AnalyticsContext):
    await ctx.prepare()
    daily = {d: (sum(v) / len(v), len(v)) for d, v in _daily_scores(_texts(await ctx.comments())).items() if len(v) >= 5}
    if len(daily) < 4:
        raise InsufficientData("нужно ≥4 дня с ≥5 эмоциональными комментариями")
    days = sorted(daily)
    diffs = [daily[days[i]][0] - daily[days[i - 1]][0] for i in range(1, len(days))]
    sd = u.std(diffs) or 0
    out = []
    for i, dlt in enumerate(diffs, start=1):
        if sd and abs(dlt) >= 2 * sd:
            out.append({"date": days[i], "tone_change": u.r4(dlt), "tone": u.r4(daily[days[i]][0]), "messages": daily[days[i]][1]})
    return {
        "days": len(days),
        "series": [{"date": d, "tone": u.r4(daily[d][0]), "messages": daily[d][1]} for d in days],
        "triggers": out,
        "method": "день, где суточная тональность меняется на ≥2σ от изменений между днями",
    }


@calculator("III.20")
async def emotions(ctx: AnalyticsContext):
    await ctx.prepare()
    rows = _texts([*await ctx.posts(), *await ctx.comments()])
    if not rows:
        raise InsufficientData("нет текстов")
    pos = sum(1 for r in rows if r.f.score > 0)
    neg = sum(1 for r in rows if r.f.score < 0)
    emo: Counter = Counter()
    for r in rows:
        emo.update(r.f.emotions)
    tot_emo = sum(emo.values())
    return {
        "messages": len(rows),
        "positive_share": u.share(pos, len(rows)),
        "negative_share": u.share(neg, len(rows)),
        "neutral_share": u.share(len(rows) - pos - neg, len(rows)),
        "emotions": {k: {"count": emo.get(k, 0), "share": u.share(emo.get(k, 0), tot_emo)} for k in lx.EMOTIONS},
        "dominant_emotion": emo.most_common(1)[0][0] if emo else None,
    }


@calculator("III.28")
async def style_over_time(ctx: AnalyticsContext):
    await ctx.prepare()
    by_m: dict[str, list] = defaultdict(list)
    for r in _texts(await ctx.comments()):
        if r.published_at:
            by_m[u.month(r.published_at)].append(r)
    if len(by_m) < 2:
        raise InsufficientData("нужно ≥2 месяца комментариев")
    rows = []
    for m, rs in sorted(by_m.items()):
        wl = [len(w) for r in rs for w in re.findall(r"[а-яёa-z]+", r.text.lower())]
        rows.append(
            {
                "month": m,
                "comments": len(rs),
                "avg_words": u.mean([r.f.words for r in rs]),
                "avg_word_length": u.mean(wl),
                "exclamation_share": u.share(sum(1 for r in rs if r.f.exclam), len(rs)),
                "profanity_share": u.share(sum(1 for r in rs if r.f.profane), len(rs)),
                "emoji_share": u.share(sum(1 for r in rs if r.f.emojis), len(rs)),
            }
        )
    return {"months": rows}


@calculator("III.36")
async def profanity(ctx: AnalyticsContext):
    await ctx.prepare()
    out = {}
    for name, rows in (("comments", _texts(await ctx.comments())), ("posts", _texts(await ctx.posts()))):
        out[name] = {
            "n": len(rows),
            "share_with_profanity": u.share(sum(1 for r in rows if r.f.profane), len(rows)),
            "occurrences": sum(r.f.profane for r in rows),
        }
    return out


@calculator("III.37")
async def profanity_vs_aggression(ctx: AnalyticsContext):
    await ctx.prepare()
    rows = [r for r in _texts(await ctx.comments())]
    if len(rows) < 20:
        raise InsufficientData("меньше 20 комментариев")
    prof = [r.f.score for r in rows if r.f.profane]
    clean = [r.f.score for r in rows if not r.f.profane]
    return {
        "n": len(rows),
        "pearson_profanity_vs_tone": u.pearson([1.0 if r.f.profane else 0.0 for r in rows], [r.f.score for r in rows]),
        "mean_tone_with_profanity": u.mean(prof),
        "mean_tone_without": u.mean(clean),
        "aggression_words_in_profane": sum(r.f.aggression for r in rows if r.f.profane),
    }


@calculator("II.43", "II.45")
async def cohesion(ctx: AnalyticsContext):
    await ctx.prepare()
    comments = await ctx.comments()
    by_id = {c.id: c for c in comments}
    pos = neg = 0
    for c in comments:
        if c.parent_id in by_id and (c.f.pos + c.f.neg) > 0:
            if c.f.score > 0:
                pos += 1
            elif c.f.score < 0:
                neg += 1
    tot = pos + neg
    if tot < 10:
        raise InsufficientData(f"меньше 10 эмоциональных ответов друг другу (есть {tot})")
    balance = (pos - neg) / tot
    return {
        "replies_analyzed": tot,
        "positive_replies": pos,
        "negative_replies": neg,
        "balance": u.r4(balance),
        "level": "high" if balance > 0.2 else "low" if balance < -0.2 else "medium",
        "method": "баланс позитивных и негативных ответов участников друг другу (лексикон)",
    }


def _threads(comments):
    by_post: dict[int, list] = defaultdict(list)
    for c in comments:
        by_post[c.post_id].append(c)
    return by_post


@calculator("I.12", "II.53")
async def conflict_threads(ctx: AnalyticsContext):
    await ctx.prepare()
    posts = {p.id: p for p in await ctx.posts()}
    # посты вне окна не загружены — для ссылки берём данные, что есть
    out = []
    threads = _threads(await ctx.comments())
    for pid, cs in threads.items():
        if len(cs) < 5:
            continue
        neg_share = sum(1 for c in cs if c.f.score < 0) / len(cs)
        heat = sum(c.f.aggression + c.f.profane for c in cs) / len(cs)
        score = 0.5 * neg_share + 0.5 * min(1.0, heat)
        if score >= 0.35:
            p = posts.get(pid)
            out.append(
                {
                    "post_id": pid,
                    "url": p.url if p else None,
                    "source_id": cs[0].source_id,
                    "comments": len(cs),
                    "negative_share": u.r4(neg_share),
                    "aggression_per_comment": u.r4(heat),
                    "conflict_score": u.r4(score),
                    "snippet": (p.text[:160] if p and p.text else None),
                }
            )
    out.sort(key=lambda x: -x["conflict_score"])
    return {
        "threads_with_5plus_comments": sum(1 for cs in threads.values() if len(cs) >= 5),
        "conflict_threads": len(out),
        "top": out[:15],
        "method": "обсуждения с долей негатива и агрессивной/нецензурной лексики выше порога; классификация типа — II.50/II.51 (LLM)",
    }


@calculator("III.45", "III.44")
async def polarity_triggers(ctx: AnalyticsContext):
    await ctx.prepare()
    posts = {p.id: p for p in await ctx.posts()}
    rows = []
    for pid, cs in _threads(await ctx.comments()).items():
        scored = [c.f.score for c in cs if (c.f.pos + c.f.neg) > 0]
        if len(scored) < 5:
            continue
        sd = u.std(scored) or 0.0
        p = posts.get(pid)
        rows.append(
            {
                "post_id": pid,
                "url": p.url if p else None,
                "comments": len(cs),
                "tone_std": sd,
                "pos": sum(1 for s in scored if s > 0),
                "neg": sum(1 for s in scored if s < 0),
                "snippet": (p.text[:160] if p and p.text else None),
            }
        )
    if not rows:
        raise InsufficientData("нет обсуждений с ≥5 эмоциональными комментариями")
    rows.sort(key=lambda x: -x["tone_std"])
    return {"threads_analyzed": len(rows), "most_polarizing": rows[:15], "method": "разброс тональности комментариев внутри обсуждения"}
