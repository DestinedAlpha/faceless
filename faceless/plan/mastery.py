"""Niche mastery: resolve a per-niche *playbook* that shapes the whole run.

A playbook is an explicit, reusable recipe for making a given kind of video well:
structure, pacing, voice, visual art-direction, captions, music/sfx mood,
thumbnail/title patterns and hook formulas. Known niches load from
`playbooks/<niche>.yaml` (deep-merged over `playbooks/_base.yaml`). An UNSEEN
niche is synthesized by the LLM from the base schema + exemplar trend titles,
cached under `playbooks/generated/`, and falls back to the closest known
playbook (or the base) if the LLM is unavailable.

That combination — authored packs for known niches + on-demand synthesis for the
rest — is what lets "mastery" generalize to *any* niche the trend selector finds,
while never breaking a run when offline.

Public API:
    get_playbook(niche, topics=None, allow_synthesis=True) -> dict
"""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

from ..core.config import load_config
from ..core.log import get_logger
from ..core.util import slugify, write_json
from ..llm import client as llm

log = get_logger(__name__)
_cfg = load_config()

PLAYBOOK_DIR = _cfg.root / "playbooks"
GENERATED_DIR = PLAYBOOK_DIR / "generated"

# Hard-coded safety net so the resolver works even if _base.yaml is missing.
_FALLBACK_BASE: dict[str, Any] = {
    "niche": "generic",
    "structure": ["hook", "setup", "escalation", "payoff", "loop"],
    "pacing": {"seconds_per_scene": 4.5, "scene_count": [4, 9], "total_seconds": [30, 55]},
    "voice": {"style": "clear, engaging, confident narrator", "wpm": 160,
              "edge_voice": "en-US-AriaNeural", "edge_rate": "+6%", "edge_pitch": "+0Hz",
              "emphasis": "punch the hook and the payoff; keep the middle brisk"},
    "visual": {"art_direction": "cinematic, photoreal, dramatic lighting, 8k",
               "palette": "rich, high-contrast",
               "style_suffix": "cinematic, high detail, dramatic composition",
               "negative": "text, watermark, logo, extra fingers, deformed, blurry",
               "consistency": "keep the same subject look and style across all scenes"},
    "motion": {"parallax_intensity": 0.35, "transitions": ["fade"]},
    "captions": {"style": "clean", "position": "lower", "emphasis": True,
                 "font_family": "Inter", "max_words_per_group": 4},
    "music": {"mood": ["cinematic", "ambient"], "bpm": [80, 120]},
    "sfx": ["whoosh", "riser"],
    "thumbnail": {"style": "high-contrast, bold heavy sans, subject-forward"},
    "title": {"patterns": ["The truth about {topic}", "{topic}: what nobody tells you"]},
    "cta": "Follow for more.",
    "hook_formulas": [
        "Open with a surprising, specific claim that contradicts what people assume.",
        "Pose a curiosity-gap question the viewer needs answered.",
    ],
    "retention_targets": {"avd_pct": 0.55, "hook_hold_pct": 0.75},
}


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _deep_merge(base: dict, over: dict) -> dict:
    """Recursively merge `over` onto a copy of `base` (dicts merged, others replaced)."""
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _load_yaml(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except FileNotFoundError:
        return {}
    except Exception as exc:  # noqa: BLE001
        log.warning("[mastery] failed to read %s: %s", path.name, exc)
        return {}


def _base() -> dict:
    return _deep_merge(_FALLBACK_BASE, _load_yaml(PLAYBOOK_DIR / "_base.yaml"))


def _known_niches() -> list[str]:
    if not PLAYBOOK_DIR.exists():
        return []
    out = []
    for p in sorted(PLAYBOOK_DIR.glob("*.yaml")):
        if p.stem.startswith("_"):
            continue
        out.append(p.stem)
    return out


def _norm(niche: str) -> str:
    return slugify(niche or "generic")


def _closest_known(niche: str) -> str | None:
    """Cheap nearest-known match by shared tokens (no deps)."""
    known = _known_niches()
    if not known:
        return None
    want = set(_norm(niche).split("-"))
    best, best_score = None, 0
    for k in known:
        ktoks = set(k.split("-"))
        # exact shared tokens, plus partial (prefix/substring) token overlap
        score = len(want & ktoks)
        for a in want:
            for b in ktoks:
                if a != b and len(a) >= 4 and len(b) >= 4 and (a.startswith(b) or b.startswith(a)):
                    score += 1
        if score > best_score:
            best, best_score = k, score
    return best if best_score > 0 else None


def load_playbook(niche: str) -> dict | None:
    """Load a known niche playbook merged over base. None if the niche is unknown."""
    key = _norm(niche)
    path = PLAYBOOK_DIR / f"{key}.yaml"
    gen = GENERATED_DIR / f"{key}.yaml"
    if path.exists():
        pb = _deep_merge(_base(), _load_yaml(path))
        pb["_source"] = "authored"
        pb["niche"] = key
        return pb
    if gen.exists():
        pb = _deep_merge(_base(), _load_yaml(gen))
        pb["_source"] = "generated-cache"
        pb["niche"] = key
        return pb
    return None


# --------------------------------------------------------------------------- #
# Synthesis (unseen niches)
# --------------------------------------------------------------------------- #
_SYNTH_SYSTEM = (
    "You are a faceless-video format expert. Given a niche, you output a compact "
    "'playbook' JSON that captures how to make that niche exceptionally well: its "
    "beat structure, pacing, narrator voice style, visual art direction, caption "
    "style, music/sfx mood, thumbnail/title patterns and proven hook formulas. Be "
    "concrete and specific to the niche; optimize for watch-through and shareability; "
    "keep everything copyright-safe (no real named people's likenesses, no logos)."
)


def _synth_prompt(niche: str, base: dict, topics: list | None) -> str:
    examples = ""
    if topics:
        labels = []
        for t in topics[:6]:
            labels.append(getattr(t, "label", None) or (t.get("label") if isinstance(t, dict) else str(t)))
        examples = "Currently trending example titles in/around this space:\n- " + \
                   "\n- ".join([str(x) for x in labels if x]) + "\n\n"
    return (
        f"Create a playbook for the niche: \"{niche}\".\n\n{examples}"
        "Return JSON with EXACTLY these keys (match this shape):\n"
        f"{yaml_to_shape(base)}\n\n"
        "Rules: keep list lengths similar to the shape; wpm 140-190; "
        "seconds_per_scene 2.5-6; total_seconds a [min,max] band; captions.style one of "
        "clean|bold|brainrot; edge_voice a valid Microsoft neural voice like "
        "en-US-AriaNeural or en-US-GuyNeural. Return JSON only."
    )


def yaml_to_shape(base: dict) -> str:
    """A trimmed example of the expected structure to steer the LLM."""
    shape = {
        "niche": "example-niche",
        "structure": base["structure"],
        "pacing": base["pacing"],
        "voice": base["voice"],
        "visual": {k: base["visual"][k] for k in ("art_direction", "style_suffix",
                                                  "palette", "negative", "consistency")
                   if k in base["visual"]},
        "motion": base["motion"],
        "captions": base["captions"],
        "music": base["music"],
        "sfx": base["sfx"],
        "thumbnail": base["thumbnail"],
        "title": base["title"],
        "cta": base["cta"],
        "hook_formulas": base["hook_formulas"],
    }
    import json
    return json.dumps(shape, ensure_ascii=False, indent=1)


def _validate(pb: dict, base: dict) -> dict:
    """Merge synthesized fields over base and clamp anything wild."""
    merged = _deep_merge(base, pb or {})
    v = merged["voice"]
    try:
        v["wpm"] = int(max(140, min(190, int(v.get("wpm", 160)))))
    except (TypeError, ValueError):
        v["wpm"] = 160
    p = merged["pacing"]
    try:
        p["seconds_per_scene"] = float(max(2.5, min(6.0, float(p.get("seconds_per_scene", 4.5)))))
    except (TypeError, ValueError):
        p["seconds_per_scene"] = 4.5
    if merged.get("captions", {}).get("style") not in ("clean", "bold", "brainrot"):
        merged["captions"]["style"] = "bold"
    if not isinstance(merged.get("hook_formulas"), list) or not merged["hook_formulas"]:
        merged["hook_formulas"] = base["hook_formulas"]
    return merged


def _synthesize(niche: str, base: dict, topics: list | None) -> dict | None:
    if not llm.available():
        return None
    try:
        raw = llm.complete_json(_synth_prompt(niche, base, topics), system=_SYNTH_SYSTEM)
        pb = _validate(raw if isinstance(raw, dict) else {}, base)
        pb["niche"] = _norm(niche)
        pb["_source"] = "synthesized"
        # Cache for reuse / inspection.
        try:
            GENERATED_DIR.mkdir(parents=True, exist_ok=True)
            with open(GENERATED_DIR / f"{_norm(niche)}.yaml", "w", encoding="utf-8") as fh:
                yaml.safe_dump({k: val for k, val in pb.items() if not k.startswith("_")},
                               fh, sort_keys=False, allow_unicode=True)
        except Exception as exc:  # noqa: BLE001
            log.debug("[mastery] could not cache synthesized playbook: %s", exc)
        log.info("[mastery] synthesized a new playbook for unseen niche '%s'", niche)
        return pb
    except Exception as exc:  # noqa: BLE001
        log.warning("[mastery] synthesis failed for '%s': %s", niche, exc)
        return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def get_playbook(niche: str, topics: list | None = None,
                 allow_synthesis: bool = True) -> dict:
    """Resolve the best playbook for `niche`.

    1) authored/cached playbook if it exists,
    2) else synthesize one via the LLM (cached),
    3) else fall back to the closest known playbook,
    4) else the base playbook.
    Always returns a usable dict.
    """
    base = _base()

    pb = load_playbook(niche)
    if pb is not None:
        log.info("[mastery] using %s playbook for '%s'", pb.get("_source"), pb["niche"])
        return pb

    if allow_synthesis:
        pb = _synthesize(niche, base, topics)
        if pb is not None:
            return pb

    near = _closest_known(niche)
    if near:
        pb = load_playbook(near) or base
        pb["_source"] = f"fallback:{near}"
        log.info("[mastery] no playbook for '%s' -> nearest known '%s'", niche, near)
        return pb

    base["niche"] = _norm(niche)
    base["_source"] = "base"
    log.info("[mastery] no playbook for '%s' -> base defaults", niche)
    return base
