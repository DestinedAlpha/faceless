"""YouTube trend source: videos.list?chart=mostPopular (1 quota unit per call).

Fetches per region x category. `mostPopular` already returns snippet+statistics
in one call, so a full sweep of R regions x C categories costs R*C units — trivial
against the 10k/day free quota.
"""
from __future__ import annotations

from datetime import datetime, timezone

from ..core import http
from ..core.config import env, load_config
from ..core.log import get_logger
from .models import TrendItem

log = get_logger(__name__)
_cfg = load_config()

API = "https://www.googleapis.com/youtube/v3/videos"


def available() -> bool:
    return bool(env("YOUTUBE_API_KEY")) and _cfg.get("trends.youtube.enabled", True)


def _parse_dt(s: str) -> datetime:
    # RFC3339, e.g. 2026-07-09T12:34:56Z
    return datetime.fromisoformat(s.replace("Z", "+00:00")).astimezone(timezone.utc)


def fetch() -> list[TrendItem]:
    if not available():
        log.info("[youtube] skipped (no key or disabled)")
        return []
    key = env("YOUTUBE_API_KEY")
    regions = _cfg.get("trends.youtube.regions", ["US"])
    categories = _cfg.get("trends.youtube.categories", [0])
    max_per = int(_cfg.get("trends.youtube.max_per_call", 50))

    items: dict[str, TrendItem] = {}
    for region in regions:
        for cat in categories:
            params = {
                "part": "snippet,statistics",
                "chart": "mostPopular",
                "regionCode": region,
                "maxResults": max_per,
                "key": key,
            }
            if cat and int(cat) != 0:
                params["videoCategoryId"] = str(cat)
            try:
                data = http.get_json(API, params=params, cache=True,
                                     cache_key=f"yt:{region}:{cat}")
            except Exception as exc:  # noqa: BLE001
                log.warning("[youtube] %s/cat%s failed: %s", region, cat, exc)
                continue
            for v in data.get("items", []):
                vid = v["id"]
                sn = v.get("snippet", {})
                st = v.get("statistics", {})
                if vid in items:  # same video can top multiple region/cat lists
                    continue
                items[vid] = TrendItem(
                    source="youtube",
                    id=vid,
                    title=sn.get("title", "")[:200],
                    url=f"https://www.youtube.com/watch?v={vid}",
                    published_at=_parse_dt(sn.get("publishedAt", "1970-01-01T00:00:00Z")),
                    views=int(st.get("viewCount", 0) or 0),
                    likes=int(st.get("likeCount", 0) or 0),
                    comments=int(st.get("commentCount", 0) or 0),
                    text=(sn.get("description", "") or "")[:400],
                    origin=region,
                )
    log.info("[youtube] collected %d unique videos", len(items))
    return list(items.values())
