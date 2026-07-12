"""HTTP helpers: a shared httpx client, retry/backoff, and an on-disk cache.

The cache is keyed by (method, url, params/body) and stores raw bytes, so repeated
dev runs don't re-hit rate-limited free APIs. JSON GETs and binary downloads both
go through here.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

import httpx
from tenacity import (retry, retry_if_exception_type, stop_after_attempt,
                      wait_exponential)

from .config import load_config
from .log import get_logger

log = get_logger(__name__)

_cfg = load_config()
_TIMEOUT = _cfg.get("runtime.http_timeout", 60)
_RETRIES = _cfg.get("runtime.http_retries", 3)
_USE_CACHE = _cfg.get("runtime.use_cache", True)

_client: httpx.Client | None = None


def client() -> httpx.Client:
    global _client
    if _client is None:
        _client = httpx.Client(
            timeout=_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": "faceless-video-gen/0.1"},
        )
    return _client


def _cache_path(key_material: str) -> Path:
    h = hashlib.sha256(key_material.encode("utf-8")).hexdigest()[:32]
    d = _cfg.cache_dir / "http"
    d.mkdir(parents=True, exist_ok=True)
    return d / f"{h}.bin"


class HttpError(RuntimeError):
    pass


@retry(
    reraise=True,
    stop=stop_after_attempt(_RETRIES),
    wait=wait_exponential(multiplier=1, min=1, max=20),
    retry=retry_if_exception_type((httpx.TransportError, httpx.HTTPStatusError)),
)
def _request(method: str, url: str, **kw) -> httpx.Response:
    resp = client().request(method, url, **kw)
    # Retry on 429 / 5xx; surface 4xx immediately (bad key etc.).
    if resp.status_code == 429 or resp.status_code >= 500:
        resp.raise_for_status()
    return resp


def request_bytes(method: str, url: str, *, cache: bool | None = None,
                  cache_key: str | None = None, **kw) -> bytes:
    """Make a request and return raw body bytes, with optional disk caching."""
    use_cache = _USE_CACHE if cache is None else cache
    key = cache_key or f"{method}:{url}:{json.dumps(kw.get('params') or {}, sort_keys=True)}:{kw.get('content','')!r}"
    cpath = _cache_path(key)
    if use_cache and cpath.exists():
        return cpath.read_bytes()

    resp = _request(method, url, **kw)
    if resp.status_code >= 400:
        raise HttpError(f"{method} {url} -> {resp.status_code}: {resp.text[:200]}")
    body = resp.content
    if use_cache:
        cpath.write_bytes(body)
    return body


def get_json(url: str, *, cache: bool | None = None, cache_key: str | None = None,
             **kw) -> Any:
    raw = request_bytes("GET", url, cache=cache, cache_key=cache_key, **kw)
    return json.loads(raw)


def post_json(url: str, *, cache: bool | None = None, cache_key: str | None = None,
              **kw) -> Any:
    raw = request_bytes("POST", url, cache=cache, cache_key=cache_key, **kw)
    return json.loads(raw)


def download(url: str, dest: Path, *, cache: bool | None = None, **kw) -> Path:
    """Download a URL to `dest` (bytes cached by URL). Returns dest."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    body = request_bytes("GET", url, cache=cache, cache_key=f"dl:{url}", **kw)
    dest.write_bytes(body)
    return dest
