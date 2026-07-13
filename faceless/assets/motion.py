"""2.5D parallax plates — cut the subject from a still so Remotion can dolly the
foreground and background at different rates, turning a flat AI image into a shot
with real depth. Free and CPU-light (rembg + Pillow), per the roadmap.

For each scene image we emit two plates:
  * `<name>_fg.png` — the subject on transparency (rembg cutout);
  * `<name>_bg.jpg` — the original frame, softly blurred so the hole left behind
    the subject reads as out-of-focus depth rather than a seam.
Remotion's `Layers` renders bg under fg and moves fg more during the camera move.

This whole module is *optional*: if rembg/onnxruntime isn't installed, the model
can't load, or the cutout is degenerate (subject is ~everything or ~nothing, so
parallax wouldn't read), `build_layers` returns None and the pipeline falls back
to the flat still + Ken Burns. A parallax failure must never break a run.
"""
from __future__ import annotations

from pathlib import Path

from ..core.log import get_logger

log = get_logger(__name__)

_session = None          # cached rembg session (model load is the slow part)
_session_failed = False  # remember a hard failure so we don't retry every scene

# Parallax only reads as depth when there's a real subject AND real background to
# move it against. Outside this coverage band we skip parallax and keep the flat
# still + Ken Burns: too little = rembg found no subject (flat scene); too much =
# the subject fills the frame, leaving no background to parallax against, so it
# would just look like a double-exposed flat image.
MIN_COVERAGE = 0.06
MAX_COVERAGE = 0.72


def _get_session():
    """Lazily create (and cache) the rembg session. Returns None if unavailable."""
    global _session, _session_failed
    if _session is not None or _session_failed:
        return _session
    try:
        from rembg import new_session
        _session = new_session("u2net")
    except Exception as exc:  # noqa: BLE001  (missing dep, model download, etc.)
        log.warning("[motion] rembg unavailable, parallax disabled: %s", exc)
        _session_failed = True
        _session = None
    return _session


def _alpha_coverage(fg) -> float:
    """Fraction of pixels the cutout kept as opaque subject (0..1)."""
    alpha = fg.getchannel("A")
    hist = alpha.histogram()               # 256 buckets
    opaque = sum(hist[128:])               # treat >=128 as 'subject'
    total = fg.width * fg.height
    return (opaque / total) if total else 0.0


def _clean_matte(fg, w: int, h: int):
    """Erode + feather the cutout's alpha to kill the tell-tale rembg halo.

    rembg leaves a 1-2px fringe of background-colored pixels around the subject;
    composited over a *different* (blurred) plate that fringe reads as an ugly
    cut-out edge. We erode the alpha inward a couple pixels (MinFilter takes the
    darkest neighbor, pulling the matte in past the fringe), then Gaussian-feather
    it so the remaining edge blends softly instead of looking stamped. Applied
    ONLY here — i.e. only to scenes that passed the coverage gate and will actually
    render as parallax — so flat scenes never pay this cost.
    """
    from PIL import ImageFilter

    alpha = fg.getchannel("A")
    dim = min(w, h)
    # Erode kernel must be an odd size; scale gently with resolution and cap so
    # MinFilter stays cheap and we don't gnaw away thin subject parts (fingers).
    erode = max(3, round(dim * 0.004))
    erode = min(9, erode | 1)              # force odd
    feather = max(1.5, dim * 0.0028)       # soft edge, ~3px at 1080
    alpha = alpha.filter(ImageFilter.MinFilter(erode))
    alpha = alpha.filter(ImageFilter.GaussianBlur(feather))
    fg.putalpha(alpha)
    return fg


def cutout(image_path: Path):
    """Return a cleaned RGBA subject cutout (Pillow Image) for `image_path`, or None.

    Used by the thumbnail composer to place the subject over a fresh background.
    Unlike `build_layers` this applies NO coverage gate — a thumbnail wants the
    subject cut out whenever rembg finds one. Never raises; None means "no cutout"
    (rembg missing, no clear subject, or an error) so callers fall back cleanly.
    """
    session = _get_session()
    if session is None:
        return None
    try:
        from PIL import Image
        from rembg import remove

        src = Image.open(image_path).convert("RGBA")
        fg = remove(src, session=session)
        coverage = _alpha_coverage(fg)
        if coverage < 0.02:               # essentially nothing was cut out
            return None
        return _clean_matte(fg, src.width, src.height)
    except Exception as exc:  # noqa: BLE001
        log.warning("[motion] cutout failed for %s: %s", image_path, exc)
        return None


def build_layers(image_path: Path, out_dir: Path, index: int) -> dict | None:
    """Produce fg/bg parallax plates for one scene image.

    Returns {"fg": <name>.png, "bg": <name>.jpg} on success, else None (caller
    falls back to the flat still). Never raises for an expected failure.
    """
    session = _get_session()
    if session is None:
        return None
    try:
        from PIL import Image, ImageFilter
        from rembg import remove

        src = Image.open(image_path).convert("RGBA")
        fg = remove(src, session=session)   # RGBA cutout on transparency

        coverage = _alpha_coverage(fg)
        if not (MIN_COVERAGE <= coverage <= MAX_COVERAGE):
            # No real fg/bg separation -> parallax wouldn't read as depth. Skip and
            # keep the reliable flat still + Ken Burns path for this scene.
            log.info("[motion] scene %d cutout coverage %.2f outside [%.2f,%.2f] -> skip parallax",
                     index, coverage, MIN_COVERAGE, MAX_COVERAGE)
            return None

        # Clean the matte (erode+feather) now that we've committed to parallax.
        fg = _clean_matte(fg, src.width, src.height)

        # Background plate: the original frame, softly blurred. The blur both sells
        # depth-of-field and hides the silhouette the subject leaves behind.
        radius = max(6, round(min(src.width, src.height) * 0.012))
        bg = src.convert("RGB").filter(ImageFilter.GaussianBlur(radius))

        fg_name = f"scene_{index:02d}_fg.png"
        bg_name = f"scene_{index:02d}_bg.jpg"
        fg.save(out_dir / fg_name)
        bg.save(out_dir / bg_name, quality=90)
        log.info("[motion] scene %d parallax plates ok (subject %.0f%%)",
                 index, coverage * 100)
        return {"fg": fg_name, "bg": bg_name}
    except Exception as exc:  # noqa: BLE001
        log.warning("[motion] scene %d parallax failed: %s", index, exc)
        return None
