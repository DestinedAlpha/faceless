"""Composite TopicScore + lightweight clustering + cross-platform corroboration.

Per item:
    view_velocity = views / age_hours
    comment_rate  = comments / views
    like_ratio    = likes / views
    recency_decay = 0.5 ** (age_hours / halflife)

Velocity/comment/like signals are percentile-normalized *within each source* so
YouTube's millions and Reddit's thousands become comparable. The four normalized
signals are combined with the configured weights. Items are then clustered into
topics by shared significant title tokens; a topic corroborated on >=2 platforms
gets a score boost.
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

from ..core.config import load_config
from ..core.log import get_logger
from .models import Topic, TrendItem

log = get_logger(__name__)
_cfg = load_config()

_STOP = set("""
a an the of to in on for and or but with without your you my our their his her its it
this that these those is are was were be been being as at by from into over under about
how why what when who whom which whose new best top vs video shorts short reel reels
just like get got make made will can now new 2024 2025 2026 official full part
""".split())


def _tokens(title: str) -> list[str]:
    words = re.findall(r"[a-zA-Z][a-zA-Z0-9']+", title.lower())
    return [w for w in words if len(w) >= 3 and w not in _STOP]


def _percentile_ranks(values: list[float]) -> list[float]:
    """Map values to [0,1] by rank (ties share the average rank). Robust to outliers."""
    n = len(values)
    if n == 0:
        return []
    if n == 1:
        return [1.0]
    order = sorted(range(n), key=lambda i: values[i])
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j + 1 < n and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = avg_rank / (n - 1)
        i = j + 1
    return ranks


def score_items(items: list[TrendItem]) -> list[TrendItem]:
    if not items:
        return items
    w = _cfg.get("trends.score_weights", {})
    w_vv = w.get("view_velocity", 0.45)
    w_cr = w.get("comment_rate", 0.20)
    w_lr = w.get("like_ratio", 0.15)
    w_rd = w.get("recency_decay", 0.20)
    halflife = float(_cfg.get("trends.recency_halflife_hours", 48))

    by_source: dict[str, list[TrendItem]] = defaultdict(list)
    for it in items:
        by_source[it.source].append(it)

    for _src, group in by_source.items():
        vv = [it.views / it.age_hours for it in group]
        cr = [it.comments / max(it.views, 1) for it in group]
        lr = [it.likes / max(it.views, 1) for it in group]
        vv_n, cr_n, lr_n = (_percentile_ranks(vv), _percentile_ranks(cr),
                            _percentile_ranks(lr))
        for i, it in enumerate(group):
            rd = 0.5 ** (it.age_hours / halflife)
            it.score = (w_vv * vv_n[i] + w_cr * cr_n[i]
                        + w_lr * lr_n[i] + w_rd * rd)
    return items


def cluster_topics(items: list[TrendItem]) -> list[Topic]:
    """Union-find clustering: link items sharing >=2 significant title tokens."""
    n = len(items)
    tokens = [set(_tokens(it.title)) for it in items]

    parent = list(range(n))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        parent[find(a)] = find(b)

    # Invert: token -> item indices, then link items that co-occur on a token.
    token_index: dict[str, list[int]] = defaultdict(list)
    for i, toks in enumerate(tokens):
        for t in toks:
            token_index[t].append(i)

    for _tok, idxs in token_index.items():
        for k in range(1, len(idxs)):
            a, b = idxs[0], idxs[k]
            if len(tokens[a] & tokens[b]) >= 2:  # need 2 shared tokens to merge
                union(a, b)

    groups: dict[int, list[int]] = defaultdict(list)
    for i in range(n):
        groups[find(i)].append(i)

    boost = float(_cfg.get("trends.cross_platform_boost", 1.25))
    min_size = int(_cfg.get("trends.min_cluster_size", 1))

    topics: list[Topic] = []
    for _root, idxs in groups.items():
        members = [items[i] for i in idxs]
        if len(members) < min_size:
            continue
        members.sort(key=lambda x: x.score, reverse=True)
        sources = {m.source for m in members}
        # aggregate keywords
        kw_counter: Counter[str] = Counter()
        for m in members:
            kw_counter.update(_tokens(m.title))
        keywords = [w for w, _ in kw_counter.most_common(10)]

        base = members[0].score + 0.04 * math.log1p(len(members) - 1)
        topic_score = base * (boost if len(sources) >= 2 else 1.0)

        topics.append(Topic(
            label=members[0].title,
            keywords=keywords,
            items=members,
            score=topic_score,
            sources=sources,
        ))

    topics.sort(key=lambda t: t.score, reverse=True)
    return topics


def discover(items: list[TrendItem]) -> list[Topic]:
    """Full pipeline: score items, cluster into ranked topics, return top-N."""
    score_items(items)
    topics = cluster_topics(items)
    top_n = int(_cfg.get("trends.top_n_topics", 15))
    ranked = topics[:top_n]
    log.info("[score] %d items -> %d topics (returning top %d)",
             len(items), len(topics), len(ranked))
    return ranked
