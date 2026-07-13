"""Per-scene AI stills: Pollinations (no key, primary) -> Cloudflare Flux (backup).

Pollinations serves an image directly from a GET on the prompt URL — no key, no
quota gate — which is why it's primary. Cloudflare Workers AI (Flux) is the backup
when a key is configured.

Phase 2 adds a *consistency* layer so scenes read as one piece instead of a set of
unrelated stills: a per-run **style anchor** (locked art-direction + a short
character/style sheet) is threaded into every prompt, negative terms suppress the
usual text/watermark/anatomy artifacts, and a **seed family** (one base seed + the
scene index) keeps the look/palette coherent while still varying composition.
"""
from __future__ import annotations

import base64
import hashlib
import urllib.parse
from pathlib import Path

from ..core import http
from ..core.config import env, load_config
from ..core.fallback import Provider, try_providers
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()


def run_seed(text: str) -> int:
    """Deterministic base seed for a run so a locked 'seed family' (base + scene
    index) gives a consistent style/palette across scenes while composition varies."""
    h = hashlib.sha1(text.encode("utf-8")).hexdigest()
    return int(h[:8], 16) % 1_000_000


def compose_prompt(prompt: str, style_anchor: str = "", negative: str = "") -> str:
    """Build the final text-to-image prompt: the scene prompt, reinforced with the
    run's locked style anchor (dropped when already present), plus negative terms
    folded in as a suffix (the free Flux endpoints ignore a separate negative field,
    so we bake it into the prompt where it still meaningfully steers the model)."""
    parts = [prompt.strip()]
    if style_anchor and style_anchor.lower() not in prompt.lower():
        parts.append(style_anchor.strip())
    full = ", ".join(p for p in parts if p)
    neg = negative.strip().strip(",")
    if neg:
        full = f"{full}. Avoid: {neg}"
    return full


def _pollinations(prompt: str, out_path: Path, width: int, height: int, seed: int) -> Path:
    model = _cfg.get("providers.images.pollinations_model", "flux")
    enc = urllib.parse.quote(prompt, safe="")
    url = (f"https://image.pollinations.ai/prompt/{enc}"
           f"?width={width}&height={height}&model={model}&nologo=true&seed={seed}")
    http.download(url, out_path, cache=True)
    if out_path.stat().st_size < 1024:  # guard against error stubs
        raise RuntimeError("pollinations returned an empty/too-small image")
    return out_path


def _cloudflare(prompt: str, out_path: Path, width: int, height: int, seed: int) -> Path:
    acct = env("CLOUDFLARE_ACCOUNT_ID")
    token = env("CLOUDFLARE_API_TOKEN")
    if not (acct and token):
        raise RuntimeError("cloudflare creds not set")
    url = (f"https://api.cloudflare.com/client/v4/accounts/{acct}"
           f"/ai/run/@cf/black-forest-labs/flux-1-schnell")
    data = http.post_json(
        url, json={"prompt": prompt, "seed": seed},
        headers={"Authorization": f"Bearer {token}"}, cache=True,
    )
    b64 = data.get("result", {}).get("image")
    if not b64:
        raise RuntimeError(f"cloudflare no image: {str(data)[:150]}")
    out_path.write_bytes(base64.b64decode(b64))
    return out_path


def _providers(prompt: str, out_path: Path, width: int, height: int, seed: int):
    order = _cfg.get("providers.images.order", ["pollinations", "cloudflare"])
    impls = {
        "pollinations": Provider("pollinations",
                                 lambda: _pollinations(prompt, out_path, width, height, seed),
                                 available=True),
        "cloudflare": Provider("cloudflare",
                               lambda: _cloudflare(prompt, out_path, width, height, seed),
                               available=bool(env("CLOUDFLARE_ACCOUNT_ID") and env("CLOUDFLARE_API_TOKEN"))),
    }
    return [impls[n] for n in order if n in impls]


def generate(prompt: str, out_path: Path, width: int, height: int, seed: int = 0,
             *, style_anchor: str = "", negative: str = "") -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    full = compose_prompt(prompt, style_anchor, negative)
    return try_providers("images", _providers(full, out_path, width, height, seed))
