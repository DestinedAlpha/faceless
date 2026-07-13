"""YouTube Data + Analytics pull over OAuth (free, one-time consent).

This is the *automated* side of the learn loop: given a one-time Google OAuth
consent, it lists your channel's recent uploads and pulls per-video retention/
engagement metrics. It is entirely optional — the loop also accepts metrics you
paste by hand from YouTube Studio (see `ingest.py`), so nothing here is required
to make the system better; it just removes the manual copy step.

Design rules honoring the project constraints:
  - 100% free: Google/YouTube Data + Analytics APIs are free; only a one-time
    OAuth token (stored locally under memory/) is needed. No card, no paid tier.
  - Never breaks a run: the google client libs are imported lazily and
    `available()` guards every entry point, so a machine without them (or without
    a client_secret) simply can't `pull` — it never raises into the pipeline.
  - Read-only: scopes are the readonly analytics + readonly data scopes. This
    module cannot upload, edit, or delete anything.

Public API:
    available() -> bool
    authenticate() -> creds            # runs the consent flow / refreshes token
    list_uploads(max_results) -> list[dict]   # {video_id, title, published_at}
    video_metrics(video_id, *, lookback_days) -> dict   # the METRIC_FIELDS
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..core.config import env, load_config
from ..core.log import get_logger
from .store import METRIC_FIELDS, MEMORY_DIR

log = get_logger(__name__)
_cfg = load_config()

_SCOPES_DEFAULT = [
    "https://www.googleapis.com/auth/yt-analytics.readonly",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _scopes() -> list[str]:
    return _cfg.get("learn.oauth.scopes", _SCOPES_DEFAULT) or _SCOPES_DEFAULT


def _client_secret_path() -> Path | None:
    """Google OAuth 'Desktop app' client_secret.json — from config or env."""
    raw = (_cfg.get("learn.oauth.client_secret", "") or ""
           ).strip() or env("YOUTUBE_OAUTH_CLIENT_SECRET")
    if not raw:
        # Convenience default: drop the file at memory/client_secret.json.
        default = MEMORY_DIR / "client_secret.json"
        return default if default.exists() else None
    p = Path(raw)
    if not p.is_absolute():
        p = _cfg.root / p
    return p if p.exists() else None


def _token_path() -> Path:
    raw = _cfg.get("learn.oauth.token_store", "memory/.oauth_token.json")
    p = Path(raw)
    if not p.is_absolute():
        p = _cfg.root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _libs():
    """Lazy import of the optional google client stack. Returns a namespace or None."""
    try:
        from google.auth.transport.requests import Request  # type: ignore
        from google.oauth2.credentials import Credentials  # type: ignore
        from google_auth_oauthlib.flow import InstalledAppFlow  # type: ignore
        from googleapiclient.discovery import build  # type: ignore
        return {"Request": Request, "Credentials": Credentials,
                "InstalledAppFlow": InstalledAppFlow, "build": build}
    except Exception as exc:  # noqa: BLE001
        log.debug("[yt] google client libs unavailable: %s", exc)
        return None


def available() -> bool:
    """True only if the libs are installed AND a client_secret is present."""
    return _libs() is not None and _client_secret_path() is not None


# --------------------------------------------------------------------------- #
# Auth
# --------------------------------------------------------------------------- #
def authenticate(*, interactive: bool = True):
    """Return valid OAuth credentials, running the one-time consent if needed.

    The token is cached at memory/.oauth_token.json and silently refreshed on
    later runs, so consent is genuinely one-time. Raises RuntimeError with an
    actionable message if the loop can't proceed (missing libs / secret).
    """
    libs = _libs()
    if libs is None:
        raise RuntimeError(
            "google client libs not installed. `pip install google-auth-oauthlib "
            "google-api-python-client` to enable automated analytics pull, or paste "
            "metrics into memory/metrics_inbox.jsonl for the manual path.")
    secret = _client_secret_path()
    if secret is None:
        raise RuntimeError(
            "no OAuth client_secret.json. Create a free 'Desktop app' OAuth client at "
            "console.cloud.google.com (enable YouTube Data + Analytics APIs), download it "
            "to memory/client_secret.json (or set learn.oauth.client_secret).")

    Credentials = libs["Credentials"]
    Request = libs["Request"]
    creds = None
    tok = _token_path()
    if tok.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(tok), _scopes())
        except Exception as exc:  # noqa: BLE001
            log.warning("[yt] cached token unreadable, re-consenting: %s", exc)
            creds = None
    if creds and creds.valid:
        return creds
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            tok.write_text(creds.to_json(), encoding="utf-8")
            return creds
        except Exception as exc:  # noqa: BLE001
            log.warning("[yt] token refresh failed, re-consenting: %s", exc)
    if not interactive:
        raise RuntimeError("no valid token and interactive consent disabled")
    flow = libs["InstalledAppFlow"].from_client_secrets_file(str(secret), _scopes())
    creds = flow.run_local_server(port=0)
    tok.write_text(creds.to_json(), encoding="utf-8")
    log.info("[yt] OAuth consent complete; token cached at %s", tok.name)
    return creds


def _service(creds, name: str, version: str):
    return _libs()["build"](name, version, credentials=creds, cache_discovery=False)


# --------------------------------------------------------------------------- #
# Data pull
# --------------------------------------------------------------------------- #
def list_uploads(max_results: int = 50, *, creds=None) -> list[dict]:
    """Return recent uploads {video_id, title, published_at}, newest first."""
    creds = creds or authenticate()
    yt = _service(creds, "youtube", "v3")
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    items = ch.get("items", [])
    if not items:
        return []
    uploads_pl = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    out: list[dict] = []
    page = None
    while len(out) < max_results:
        resp = yt.playlistItems().list(
            part="snippet,contentDetails", playlistId=uploads_pl,
            maxResults=min(50, max_results - len(out)), pageToken=page).execute()
        for it in resp.get("items", []):
            snip = it.get("snippet", {})
            out.append({
                "video_id": it["contentDetails"]["videoId"],
                "title": snip.get("title", ""),
                "published_at": it["contentDetails"].get("videoPublishedAt")
                or snip.get("publishedAt"),
            })
        page = resp.get("nextPageToken")
        if not page:
            break
    return out[:max_results]


# Analytics metric name -> our normalized field.
_METRIC_MAP = {
    "views": "views",
    "estimatedMinutesWatched": "_minutes",
    "averageViewDuration": "average_view_duration",
    "averageViewPercentage": "average_view_percentage",
    "likes": "likes",
    "comments": "comments",
    "subscribersGained": "subs_gained",
}


def video_metrics(video_id: str, *, lookback_days: int | None = None, creds=None) -> dict:
    """Pull the METRIC_FIELDS for one video over the lookback window.

    Uses two Analytics queries: the core watch/engagement metrics, and (best
    effort) impressions + CTR which live on the advertising/reach metric family
    and can be absent for some videos — those degrade to None rather than failing.
    """
    creds = creds or authenticate()
    ya = _service(creds, "youtubeAnalytics", "v2")
    days = int(lookback_days or _cfg.get("learn.lookback_days", 28))
    # Analytics needs an explicit range; use a wide, safe historical window.
    start = "2005-02-14"  # YouTube's birthday: guarantees "since upload".
    end_days_ago = 0
    from datetime import date, timedelta  # local import keeps module import light
    end = (date.today() - timedelta(days=end_days_ago)).isoformat()

    result = {k: None for k in METRIC_FIELDS}

    def _query(metrics: str) -> dict:
        return ya.reports().query(
            ids="channel==MINE", startDate=start, endDate=end,
            metrics=metrics, filters=f"video=={video_id}").execute()

    try:
        core = _query(",".join(_METRIC_MAP.keys()))
        headers = [h["name"] for h in core.get("columnHeaders", [])]
        rows = core.get("rows", [])
        if rows:
            vals = dict(zip(headers, rows[0]))
            for api_name, field in _METRIC_MAP.items():
                if field.startswith("_"):
                    continue
                result[field] = vals.get(api_name)
    except Exception as exc:  # noqa: BLE001
        log.warning("[yt] core metrics query failed for %s: %s", video_id, exc)

    # Impressions + CTR (reach metrics) — optional; ignore if unavailable.
    try:
        reach = _query("impressions,impressionsClickThroughRate")
        headers = [h["name"] for h in reach.get("columnHeaders", [])]
        rows = reach.get("rows", [])
        if rows:
            vals = dict(zip(headers, rows[0]))
            result["impressions"] = vals.get("impressions")
            ctr = vals.get("impressionsClickThroughRate")
            # API returns a fraction; normalize to a percentage for the store.
            result["ctr"] = round(ctr * 100, 2) if isinstance(ctr, (int, float)) else None
    except Exception as exc:  # noqa: BLE001
        log.debug("[yt] reach metrics unavailable for %s: %s", video_id, exc)

    # 3s retention: audienceWatchRatio at the very start (best effort).
    try:
        curve = ya.reports().query(
            ids="channel==MINE", startDate=start, end=end, endDate=end,
            metrics="audienceWatchRatio", dimensions="elapsedVideoTimeRatio",
            filters=f"video=={video_id}").execute()
        rows = curve.get("rows", [])
        if rows:
            # First bucket ~ the opening; store as a 0-100 percentage.
            first = rows[0][1] if len(rows[0]) > 1 else None
            result["retention_3s"] = round(first * 100, 1) if isinstance(
                first, (int, float)) else None
    except Exception as exc:  # noqa: BLE001
        log.debug("[yt] retention curve unavailable for %s: %s", video_id, exc)

    return result
