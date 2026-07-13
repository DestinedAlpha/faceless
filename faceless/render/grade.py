"""Per-niche color grade — a signature 'look' each niche carries into the render.

A grade is just a handful of numbers the Remotion side turns into a CSS filter
stack (contrast/saturate/brightness/sepia/hue) plus a vignette and film-grain
overlay — all free and GPU-free. This gives, say, historical-pov a warm, grainy,
vignetted film look while explainer stays clean and crisp, without touching the
images themselves.

Resolution order (so mastery generalizes to ANY niche the selector finds):
  1. an explicit `grade:` block in the playbook wins outright;
  2. else a keyword heuristic over the niche name + palette + music mood picks a
     preset (warm/film, punchy, clean, moody, vibrant, ...);
  3. else the neutral base grade.
Whatever is chosen is merged over the base so a partial override is always valid.
"""
from __future__ import annotations

# Neutral, safe defaults — a light polish that never hurts an image.
_BASE = {
    "contrast": 1.06,
    "saturate": 1.08,
    "brightness": 1.0,
    "sepia": 0.0,
    "hueRotate": 0,      # degrees
    "vignette": 0.28,    # 0..1 darkness of the corners
    "grain": 0.05,       # 0..1 opacity of the film-grain overlay
}

# Named looks, selected by keyword when a playbook has no explicit grade.
_PRESETS: dict[str, dict] = {
    "film":   {"contrast": 1.12, "saturate": 0.95, "sepia": 0.18, "hueRotate": -6,
               "vignette": 0.45, "grain": 0.12},
    "punchy": {"contrast": 1.18, "saturate": 1.28, "brightness": 1.02,
               "vignette": 0.30, "grain": 0.04},
    "vibrant": {"contrast": 1.12, "saturate": 1.35, "brightness": 1.03,
                "vignette": 0.22, "grain": 0.03},
    "clean":  {"contrast": 1.04, "saturate": 1.06, "brightness": 1.02,
               "vignette": 0.14, "grain": 0.02},
    "moody":  {"contrast": 1.16, "saturate": 0.9, "brightness": 0.97, "hueRotate": 4,
               "vignette": 0.5, "grain": 0.08},
    "warm":   {"contrast": 1.1, "saturate": 1.12, "sepia": 0.1, "hueRotate": -4,
               "vignette": 0.34, "grain": 0.06},
}

# Keyword -> preset. Matched against niche name + palette + music mood text.
_KEYWORDS: list[tuple[tuple[str, ...], str]] = [
    (("historical", "history", "period", "vintage", "retro", "war", "ancient",
      "film-grain", "film grain", "somber", "orchestral"), "film"),
    (("brainrot", "hype", "trap", "energetic", "sport", "sports", "gaming"), "punchy"),
    (("explainer", "science", "tech", "how", "clean", "infographic", "crisp"), "clean"),
    (("motivational", "stoic", "discipline", "dark", "cinematic", "epic", "suspense"), "moody"),
    (("story", "fantasy", "colorful", "vivid", "dynamic"), "vibrant"),
]


def _pick_preset(niche: str, playbook: dict) -> dict:
    v = playbook.get("visual", {}) or {}
    hay = " ".join([
        str(niche or ""),
        str(v.get("palette", "")),
        str(v.get("art_direction", "")),
        " ".join(playbook.get("music", {}).get("mood", []) or []),
    ]).lower()
    for keys, name in _KEYWORDS:
        if any(k in hay for k in keys):
            return _PRESETS[name]
    return {}


def _coerce(grade: dict) -> dict:
    """Clamp to sane ranges so a hand-authored playbook grade can't blow out."""
    def f(key, lo, hi):
        try:
            return max(lo, min(hi, float(grade.get(key, _BASE[key]))))
        except (TypeError, ValueError):
            return _BASE[key]
    return {
        "contrast": round(f("contrast", 0.5, 2.0), 4),
        "saturate": round(f("saturate", 0.0, 2.5), 4),
        "brightness": round(f("brightness", 0.5, 1.5), 4),
        "sepia": round(f("sepia", 0.0, 1.0), 4),
        "hueRotate": round(f("hueRotate", -180, 180), 2),
        "vignette": round(f("vignette", 0.0, 0.85), 4),
        "grain": round(f("grain", 0.0, 0.4), 4),
    }


def resolve(playbook: dict | None, niche: str = "") -> dict:
    """Return the render-ready grade dict for this run's playbook/niche."""
    pb = playbook or {}
    explicit = pb.get("grade") or (pb.get("visual", {}) or {}).get("grade")
    chosen = dict(_BASE)
    if explicit and isinstance(explicit, dict):
        chosen.update(explicit)
    else:
        chosen.update(_pick_preset(niche or pb.get("niche", ""), pb))
    return _coerce(chosen)
