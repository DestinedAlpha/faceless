"""Shared trend data structures used across youtube/reddit/score."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


@dataclass
class TrendItem:
    """One trending item from any source, normalized for scoring."""
    source: str                 # "youtube" | "reddit"
    id: str
    title: str
    url: str
    published_at: datetime
    views: int = 0              # youtube views / reddit ~ (score used instead)
    likes: int = 0             # youtube likes / reddit upvotes
    comments: int = 0
    text: str = ""             # description / selftext (truncated)
    origin: str = ""           # region (yt) or subreddit (reddit)
    score: float = 0.0         # filled by score.py (composite TopicScore)

    @property
    def age_hours(self) -> float:
        delta = now_utc() - self.published_at
        return max(delta.total_seconds() / 3600.0, 0.1)


@dataclass
class Topic:
    """A cluster of TrendItems that describe the same underlying subject."""
    label: str                          # human-readable topic label
    keywords: list[str] = field(default_factory=list)
    items: list[TrendItem] = field(default_factory=list)
    score: float = 0.0
    sources: set[str] = field(default_factory=set)

    @property
    def size(self) -> int:
        return len(self.items)

    @property
    def cross_platform(self) -> bool:
        return len(self.sources) >= 2

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "score": round(self.score, 4),
            "size": self.size,
            "sources": sorted(self.sources),
            "keywords": self.keywords[:10],
            "examples": [
                {"source": it.source, "title": it.title, "url": it.url,
                 "views": it.views, "likes": it.likes, "comments": it.comments,
                 "age_h": round(it.age_hours, 1)}
                for it in sorted(self.items, key=lambda x: x.score, reverse=True)[:4]
            ],
        }
