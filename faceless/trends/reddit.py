"""Reddit trend source via PRAW: hot / rising / top(day) across configured subs.

Reddit gives breadth (emerging topics before they peak on YouTube) and doubles as
cross-platform corroboration. Read-only script app; 100 QPM free.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core.config import env, load_config
from ..core.log import get_logger
from .models import TrendItem

log = get_logger(__name__)
_cfg = load_config()


def available() -> bool:
    return (bool(env("REDDIT_CLIENT_ID") and env("REDDIT_CLIENT_SECRET"))
            and _cfg.get("trends.reddit.enabled", True))


def _client():
    import praw  # imported lazily so the dep is optional
    return praw.Reddit(
        client_id=env("REDDIT_CLIENT_ID"),
        client_secret=env("REDDIT_CLIENT_SECRET"),
        user_agent=env("REDDIT_USER_AGENT", "faceless-video-gen/0.1"),
        check_for_async=False,
    )


def fetch() -> list[TrendItem]:
    if not available():
        log.info("[reddit] skipped (no creds or disabled)")
        return []
    try:
        reddit = _client()
        reddit.read_only = True
    except Exception as exc:  # noqa: BLE001
        log.warning("[reddit] client init failed: %s", exc)
        return []

    subs = _cfg.get("trends.reddit.subreddits", ["all"])
    listings = _cfg.get("trends.reddit.listings", ["hot", "rising", "top"])
    limit = int(_cfg.get("trends.reddit.limit_per_listing", 40))

    items: dict[str, TrendItem] = {}
    for sub in subs:
        for listing in listings:
            try:
                sr = reddit.subreddit(sub)
                if listing == "top":
                    gen = sr.top(time_filter="day", limit=limit)
                elif listing == "rising":
                    gen = sr.rising(limit=limit)
                else:
                    gen = sr.hot(limit=limit)
                for post in gen:
                    if post.stickied or getattr(post, "over_18", False):
                        continue
                    pid = post.id
                    if pid in items:
                        continue
                    items[pid] = TrendItem(
                        source="reddit",
                        id=pid,
                        title=(post.title or "")[:200],
                        url=f"https://reddit.com{post.permalink}",
                        published_at=datetime.fromtimestamp(
                            post.created_utc, tz=timezone.utc),
                        # Reddit has no "views"; use upvotes as the velocity proxy.
                        views=int(post.score or 0),
                        likes=int(post.score or 0),
                        comments=int(post.num_comments or 0),
                        text=(getattr(post, "selftext", "") or "")[:400],
                        origin=sub,
                    )
            except Exception as exc:  # noqa: BLE001
                log.warning("[reddit] r/%s %s failed: %s", sub, listing, exc)
                continue
    log.info("[reddit] collected %d unique posts", len(items))
    return list(items.values())
