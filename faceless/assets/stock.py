"""Stock B-roll: Pexels -> Pixabay video search by scene keywords.

Optional layer. When no key is configured this returns None and the renderer just
uses the AI still for that scene. When available it fetches a portrait/landscape
clip matching the scene keywords to add real motion between AI stills.
"""
from __future__ import annotations

from pathlib import Path

from ..core import http
from ..core.config import env, load_config
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()


def available() -> bool:
    return bool(env("PEXELS_API_KEY") or env("PIXABAY_API_KEY"))


def _pexels(keywords: str, portrait: bool, out_path: Path) -> Path | None:
    key = env("PEXELS_API_KEY")
    if not key:
        return None
    orient = "portrait" if portrait else "landscape"
    data = http.get_json(
        "https://api.pexels.com/videos/search",
        params={"query": keywords, "per_page": 5, "orientation": orient},
        headers={"Authorization": key}, cache=True,
    )
    for vid in data.get("videos", []):
        files = sorted(vid.get("video_files", []),
                       key=lambda f: (f.get("width") or 0), reverse=True)
        for f in files:
            w, h = f.get("width") or 0, f.get("height") or 0
            if portrait and h >= w and f.get("link"):
                http.download(f["link"], out_path, cache=True)
                return out_path
            if not portrait and w >= h and f.get("link"):
                http.download(f["link"], out_path, cache=True)
                return out_path
    return None


def _pixabay(keywords: str, portrait: bool, out_path: Path) -> Path | None:
    key = env("PIXABAY_API_KEY")
    if not key:
        return None
    data = http.get_json(
        "https://pixabay.com/api/videos/",
        params={"key": key, "q": keywords, "per_page": 5}, cache=True,
    )
    for hit in data.get("hits", []):
        v = hit.get("videos", {})
        stream = v.get("large") or v.get("medium") or {}
        if stream.get("url"):
            http.download(stream["url"], out_path, cache=True)
            return out_path
    return None


def fetch_broll(keywords: str, out_path: Path, portrait: bool = True) -> Path | None:
    if not available():
        return None
    out_path.parent.mkdir(parents=True, exist_ok=True)
    order = _cfg.get("providers.stock.order", ["pexels", "pixabay"])
    fns = {"pexels": _pexels, "pixabay": _pixabay}
    for name in order:
        fn = fns.get(name)
        if not fn:
            continue
        try:
            res = fn(keywords, portrait, out_path)
            if res:
                log.info("[stock] %s clip for '%s'", name, keywords[:40])
                return res
        except Exception as exc:  # noqa: BLE001
            log.warning("[stock] %s failed for '%s': %s", name, keywords[:30], exc)
    return None
