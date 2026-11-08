"""Метрики социального графа (networkx): лидеры, фракции, структура влияния, повестка."""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

import networkx as nx
from sqlalchemy import select

from app.infrastructure.db.orm.models_vozd import VozdUserFriend
from app.use_case.vozd.analytics import util as u
from app.use_case.vozd.analytics.context import AnalyticsContext
from app.use_case.vozd.analytics.registry import InsufficientData, calculator

_MAX_NODES = 3000
_FRIEND_WEIGHT = 1.0


class GraphData:
    """Граф участников: рёбра — ответы/комментарии друг другу (+друзья), вес = число взаимодействий."""

    def __init__(self) -> None:
        self.g: nx.Graph = nx.Graph()
        self.replies_received: Counter = Counter()
        self.comments_by_user: Counter = Counter()
        self.tone_received: dict[str, list[float]] = defaultdict(list)
        self.post_authors: set[str] = set()
        self.names: dict[str, str] = {}
        self.truncated = False


def _uid(platform: str, ext: int) -> str:
    return f"{'vk' if platform == 'vk' else 'tg'}:{ext}"


async def build_graph(ctx: AnalyticsContext) -> GraphData:
    async def build() -> GraphData:
        await ctx.prepare()
        gd = GraphData()
        comments = await ctx.comments()
        posts = {p.id: p for p in await ctx.posts()}
        by_id = {c.id: c for c in comments}
        users = await ctx.users()

        def add_edge(a: str, b: str, w: float = 1.0) -> None:
            if a == b:
                return
            if gd.g.has_edge(a, b):
                gd.g[a][b]["weight"] += w
            else:
                gd.g.add_edge(a, b, weight=w)

        for p in posts.values():
            if p.author_id and p.author_id > 0 and not ctx.blocked(p.platform, p.author_id):
                gd.post_authors.add(_uid(p.platform, p.author_id))
        for c in comments:
            if not c.from_id or c.from_id <= 0:
                continue
            me = _uid(c.platform, c.from_id)
            gd.comments_by_user[me] += 1
            gd.g.add_node(me)
            target = None
            parent = by_id.get(c.parent_id) if c.parent_id else None
            if parent is not None and parent.from_id and parent.from_id > 0:
                if not ctx.blocked(parent.platform, parent.from_id):
                    target = _uid(parent.platform, parent.from_id)
            else:
                post = posts.get(c.post_id)
                if post is not None and post.author_id and post.author_id > 0 and not ctx.blocked(post.platform, post.author_id):
                    target = _uid(post.platform, post.author_id)
            if target and target != me:
                add_edge(me, target)
                gd.replies_received[target] += 1
                if c.f is not None and (c.f.pos + c.f.neg):
                    gd.tone_received[target].append(c.f.score)
        # дружеские связи между участниками (только VK, только внутри графа)
        vk_nodes = {n: int(n.split(":")[1]) for n in gd.g.nodes if n.startswith("vk:")}
        if vk_nodes:
            db_users = {u_.id: u_ for (pl, _), u_ in users.items() if pl == "vk"}
            ext_by_dbid = {u_.id: u_.external_id for u_ in db_users.values()}
            node_ext = set(vk_nodes.values())
            ids = list(ext_by_dbid)
            for i in range(0, len(ids), 5000):
                part = ids[i : i + 5000]
                q = select(VozdUserFriend.user_id, VozdUserFriend.friend_external_id).where(
                    VozdUserFriend.user_id.in_(part), VozdUserFriend.friend_external_id.in_(node_ext)
                )
                for uid_db, friend_ext in (await ctx.db.execute(q)).all():
                    a, b = f"vk:{ext_by_dbid[uid_db]}", f"vk:{friend_ext}"
                    if gd.g.has_node(a) and gd.g.has_node(b):
                        add_edge(a, b, _FRIEND_WEIGHT)
        for (pl, ext), usr in users.items():
            name = " ".join(x for x in (usr.first_name, usr.last_name) if x) or usr.username or ""
            gd.names[_uid(pl, ext)] = name
        if gd.g.number_of_nodes() > _MAX_NODES:
            keep = {n for n, _ in sorted(gd.g.degree(weight="weight"), key=lambda x: -x[1])[:_MAX_NODES]}
            gd.g = gd.g.subgraph(keep).copy()
            gd.truncated = True
        return gd

    return await ctx.memo("graph", build)


def _need_graph(gd: GraphData, min_nodes: int = 5) -> None:
    if gd.g.number_of_nodes() < min_nodes or gd.g.number_of_edges() < 3:
        raise InsufficientData(
            f"граф слишком мал: {gd.g.number_of_nodes()} участников, {gd.g.number_of_edges()} связей (нужно ≥{min_nodes} и ≥3)"
        )


def _person(gd: GraphData, uid: str, **extra: Any) -> dict[str, Any]:
    return {"uid": uid, "name": gd.names.get(uid) or None, **extra}


async def _centralities(ctx: AnalyticsContext, gd: GraphData) -> dict[str, dict[str, float]]:
    async def calc() -> dict[str, dict[str, float]]:
        g = gd.g
        deg = dict(g.degree(weight="weight"))
        k = min(200, g.number_of_nodes())
        betw = nx.betweenness_centrality(g, k=k if k < g.number_of_nodes() else None, weight=None, seed=1)
        try:
            eig = nx.eigenvector_centrality_numpy(g, weight="weight")
        except Exception:  # noqa: BLE001 — вырожденный граф или нет scipy
            try:
                eig = nx.eigenvector_centrality(g, weight="weight", max_iter=500)
            except Exception:  # noqa: BLE001
                eig = nx.degree_centrality(g)
        return {"degree": deg, "betweenness": betw, "eigenvector": eig}

    return await ctx.memo("centralities", calc)


@calculator("1.11")
async def leaders(ctx: AnalyticsContext):
    gd = await build_graph(ctx)
    _need_graph(gd)
    c = await _centralities(ctx, gd)
    top = sorted(gd.g.nodes, key=lambda n: -c["eigenvector"].get(n, 0))[:20]
    return {
        "nodes": gd.g.number_of_nodes(),
        "edges": gd.g.number_of_edges(),
        "truncated_to_top_nodes": gd.truncated,
        "leaders": [
            _person(
                gd,
                n,
                eigenvector=u.r4(c["eigenvector"].get(n), 5),
                betweenness=u.r4(c["betweenness"].get(n), 5),
                weighted_degree=c["degree"].get(n),
                replies_received=gd.replies_received.get(n, 0),
                comments=gd.comments_by_user.get(n, 0),
                posts_author=n in gd.post_authors,
            )
            for n in top
        ],
        "method": "центральность по собственному вектору и посредничеству на графе ответов и дружбы",
    }


@calculator("1.10")
async def subgroups(ctx: AnalyticsContext):
    gd = await build_graph(ctx)
    _need_graph(gd)
    g = gd.g
    comps = nx.community.louvain_communities(g, weight="weight", seed=1)
    comps = sorted(comps, key=len, reverse=True)
    mod = nx.community.modularity(g, comps, weight="weight")
    deg = dict(g.degree(weight="weight"))
    out = []
    for i, comp in enumerate(comps[:10], start=1):
        members = sorted(comp, key=lambda n: -deg.get(n, 0))
        out.append(
            {
                "community": i,
                "size": len(comp),
                "share": u.share(len(comp), g.number_of_nodes()),
                "core": [_person(gd, n, weighted_degree=deg.get(n)) for n in members[:5]],
            }
        )
    return {
        "communities_total": len(comps),
        "modularity": u.r4(mod),
        "isolated_nodes": sum(1 for n in g.nodes if g.degree(n) == 0),
        "top_communities": out,
        "method": "Louvain на графе ответов и дружбы; modularity >0.3 — выраженное разделение на фракции",
    }


@calculator("2.35")
async def leaders_quantitative(ctx: AnalyticsContext):
    gd = await build_graph(ctx)
    if not gd.comments_by_user:
        raise InsufficientData("нет комментариев участников")
    posts = await ctx.posts()
    authored: Counter = Counter()
    engagement: Counter = Counter()
    for p in posts:
        if p.author_id and p.author_id > 0 and not ctx.blocked(p.platform, p.author_id):
            uid = _uid(p.platform, p.author_id)
            authored[uid] += 1
            engagement[uid] += p.engagement
    score = Counter()
    for uid in set(gd.comments_by_user) | set(authored):
        score[uid] = gd.comments_by_user.get(uid, 0) + 2 * gd.replies_received.get(uid, 0) + engagement.get(uid, 0)
    return {
        "leaders": [
            _person(
                gd,
                uid,
                score=s,
                comments=gd.comments_by_user.get(uid, 0),
                replies_received=gd.replies_received.get(uid, 0),
                posts_authored=authored.get(uid, 0),
                posts_engagement=engagement.get(uid, 0),
            )
            for uid, s in score.most_common(20)
        ],
        "score": "комментарии + 2×полученные ответы + вовлечённость собственных постов",
    }


@calculator("2.36")
async def leaders_qualitative(ctx: AnalyticsContext):
    gd = await build_graph(ctx)
    cands = [n for n, k in gd.replies_received.most_common(30) if len(gd.tone_received.get(n, [])) >= 3]
    if not cands:
        raise InsufficientData("нет участников с ≥3 эмоциональными ответами")
    return {
        "leaders": [
            _person(
                gd,
                n,
                replies_received=gd.replies_received[n],
                avg_tone_of_replies=u.mean(gd.tone_received[n]),
                tone_std=u.std(gd.tone_received[n]),
            )
            for n in cands[:20]
        ],
        "note": "тональность ответов на комментарии/посты лидера (лексикон); экспертность и харизму оценивает эксперт",
    }


@calculator("2.37")
async def leader_types(ctx: AnalyticsContext):
    gd = await build_graph(ctx)
    _need_graph(gd)
    c = await _centralities(ctx, gd)
    ranked = sorted(gd.g.nodes, key=lambda n: -c["eigenvector"].get(n, 0))[:30]
    formal, informal, polarizing = [], [], []
    for n in ranked:
        tones = gd.tone_received.get(n, [])
        row = _person(gd, n, eigenvector=u.r4(c["eigenvector"].get(n), 5), replies_received=gd.replies_received.get(n, 0))
        if n in gd.post_authors:
            formal.append(row)
        else:
            informal.append(row)
        if len(tones) >= 5 and (u.std(tones) or 0) >= 0.7:
            polarizing.append({**row, "tone_std": u.std(tones)})
    return {
        "formal_authors": formal[:10],
        "informal": informal[:10],
        "polarizing": polarizing[:10],
        "note": "формальные = люди-авторы постов в источниках группы (список администраторов не собирается); "
        "неформальные = высокая центральность без постов; поляризующие = центральность + большой разброс тональности ответов",
    }


@calculator("2.39", "2.40", "2.41")
async def influence_structure(ctx: AnalyticsContext):
    gd = await build_graph(ctx)
    _need_graph(gd)
    g = gd.g
    deg = dict(g.degree(weight="weight"))
    total = sum(deg.values()) or 1
    ranked = sorted(deg.values(), reverse=True)
    top1, top3 = ranked[0] / total, sum(ranked[:3]) / total
    g_ = u.gini(deg.values())
    n = g.number_of_nodes()
    dmax = max(dict(g.degree()).values())
    freeman = (
        sum(dmax - d for d in dict(g.degree()).values()) / ((n - 1) * (n - 2)) if n > 2 else None
    )
    if (g_ or 0) >= 0.7 and top1 >= 0.1:
        label = "centralized"
    elif (g_ or 1) <= 0.4:
        label = "decentralized"
    else:
        label = "hybrid"
    wanted = {"2.39": "centralized", "2.40": "decentralized", "2.41": "hybrid"}.get(ctx.metric_id)
    return {
        "structure": label,
        "matches_requested": (label == wanted) if wanted else None,
        "top1_share_of_interactions": u.r4(top1),
        "top3_share_of_interactions": u.r4(top3),
        "gini_weighted_degree": g_,
        "freeman_degree_centralization": u.r4(freeman),
        "nodes": n,
        "edges": g.number_of_edges(),
        "thresholds": "centralized: Gini ≥0.7 и доля лидера ≥10%; decentralized: Gini ≤0.4; иначе hybrid",
    }


@calculator("3.48")
async def agenda_setters(ctx: AnalyticsContext):
    posts = await ctx.posts()
    gd = await build_graph(ctx)
    comments_by_post = Counter(c.post_id for c in await ctx.comments())
    agg: dict[str, dict[str, int]] = defaultdict(lambda: {"posts": 0, "comments_received": 0})
    community_posts = 0
    for p in posts:
        if p.author_id and p.author_id > 0 and not ctx.blocked(p.platform, p.author_id):
            uid = _uid(p.platform, p.author_id)
            agg[uid]["posts"] += 1
            agg[uid]["comments_received"] += comments_by_post.get(p.id, 0)
        else:
            community_posts += 1
    if not agg:
        raise InsufficientData("посты в источниках опубликованы от имени сообществ — авторов-людей нет")
    ranked = sorted(agg.items(), key=lambda kv: -kv[1]["comments_received"])[:15]
    return {
        "setters": [_person(gd, uid, **v, avg_resonance=u.r4(v["comments_received"] / v["posts"])) for uid, v in ranked],
        "posts_by_communities": community_posts,
        "note": "резонанс = комментарии под постами автора-человека",
    }
