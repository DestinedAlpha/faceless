"""Aggregate all trend sources and return ranked Topics.

Real runs pull YouTube + Reddit. If no source is available (no keys) and
`allow_synthetic` is set, we fall back to a small synthetic pool so the rest of
the pipeline can be exercised end-to-end offline. Synthetic items are clearly
flagged and are never used when a real source is configured.
"""
from __future__ import annotations

from datetime import timedelta

from ..core.log import get_logger
from . import reddit, youtube
from .models import Topic, TrendItem, now_utc
from .score import discover

log = get_logger(__name__)


def _synthetic_pool() -> list[TrendItem]:
    """Offline test fixture — NOT production topics. Loosely evergreen faceless niches."""
    seeds = [
        ("The forgotten empire that vanished overnight", 1_800_000, 120_000, 9_000, 6),
        ("Why the deepest part of the ocean terrifies scientists", 2_400_000, 190_000, 14_000, 10),
        ("A day in the life of a Roman soldier", 3_100_000, 240_000, 12_000, 20),
        ("The psychology trick that makes people trust you", 1_200_000, 95_000, 7_500, 4),
        ("How one decision built the richest dynasty in history", 900_000, 61_000, 5_100, 14),
    ]
    base = now_utc()
    items: list[TrendItem] = []
    for i, (title, views, likes, comments, age_h) in enumerate(seeds):
        items.append(TrendItem(
            source="synthetic", id=f"syn{i}", title=title,
            url="", published_at=base - timedelta(hours=age_h),
            views=views, likes=likes, comments=comments, origin="offline",
        ))
    return items


def collect_items() -> list[TrendItem]:
    items: list[TrendItem] = []
    items += youtube.fetch()
    items += reddit.fetch()
    return items


def find_topics(allow_synthetic: bool = True) -> list[Topic]:
    items = collect_items()
    if not items:
        if allow_synthetic:
            log.warning("[trends] no real source available -> using SYNTHETIC test pool")
            items = _synthetic_pool()
        else:
            log.error("[trends] no trend data and synthetic disabled")
            return []
    return discover(items)
