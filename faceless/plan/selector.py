"""Selector: the LLM decides EVERYTHING about packaging from ranked trends.

Given the ranked topics + policy (allowed niches, format bounds), the model picks
the single best topic, its niche, whether it should be a Short or long-form, the
target length, visual style and voice delivery — all justified by the trend signals.
Nothing about the topic is hardcoded. If no LLM is available, a transparent
heuristic fallback picks the top-ranked topic and maps a niche by keywords.
"""
from __future__ import annotations

from ..core.config import load_config
from ..core.log import get_logger
from ..llm import client as llm
from ..trends.models import Topic
from .schemas import SELECTION_SCHEMA

log = get_logger(__name__)
_cfg = load_config()

_SYSTEM = (
    "You are the content strategist for a faceless YouTube/Shorts channel. You choose "
    "what to make next based ONLY on real trend data provided to you. You optimize for "
    "watch-through and shareability, and you keep every choice copyright-safe (AI imagery "
    "+ stock, never reused copyrighted clips). Be decisive."
)


def _prompt(topics: list[Topic]) -> str:
    allow = _cfg.get("policy.allow_niches", [])
    blocked = _cfg.get("policy.blocked_terms", [])
    fmt = _cfg.get("format", {})
    ranked = "\n".join(
        f"{i+1}. score={t.score:.3f} sources={sorted(t.sources)} "
        f"size={t.size} :: {t.label}  [keywords: {', '.join(t.keywords[:8])}]"
        for i, t in enumerate(topics)
    )
    return f"""Here are the top trending topic clusters right now, already scored and ranked
(higher score = stronger real engagement velocity + corroboration):

{ranked}

Allowed niches (pick exactly one): {allow}
Never touch anything involving: {blocked}

Format bounds:
- short (9:16): {fmt.get('short', {}).get('min_seconds')}-{fmt.get('short', {}).get('max_seconds')}s
- long (16:9): {fmt.get('long', {}).get('min_seconds')}-{fmt.get('long', {}).get('max_seconds')}s

Decide the single best video to make next. Choose the format that best fits THIS topic
and maximizes retention (a punchy curiosity topic -> short; a topic with real depth ->
long). Refine the topic into a specific, compelling angle. Return JSON only."""


def _heuristic(topics: list[Topic]) -> dict:
    """No-LLM fallback: top topic + keyword->niche mapping + short default."""
    top = topics[0]
    allow = _cfg.get("policy.allow_niches", ["explainer"])
    kws = set(top.keywords)
    mapping = [
        ({"history", "empire", "ancient", "roman", "dynasty", "king", "war"}, "historical-pov"),
        ({"psychology", "trick", "trust", "mind", "brain", "habit"}, "explainer"),
        ({"ocean", "space", "science", "universe", "deep"}, "science-facts"),
        ({"discipline", "success", "rich", "grind", "stoic"}, "motivational"),
        ({"top", "best", "ranked", "list"}, "top-list"),
    ]
    niche = "explainer"
    for keys, n in mapping:
        if kws & keys and n in allow:
            niche = n
            break
    if niche not in allow and allow:
        niche = allow[0]
    return {
        "topic": top.label,
        "niche": niche,
        "format": _cfg.get("format.default_kind", "short"),
        "target_seconds": 40,
        "style": "cinematic, high-contrast, dramatic lighting, photoreal AI stills",
        "voice_style": "suspenseful and engaging",
        "hook_angle": "open loop / curiosity gap",
        "rationale": f"Heuristic fallback: highest-scoring trend ({top.score:.3f}).",
    }


def select(topics: list[Topic]) -> dict:
    if not topics:
        raise ValueError("no topics to select from")
    if llm.available():
        try:
            choice = llm.complete_json(_prompt(topics), schema=SELECTION_SCHEMA,
                                       system=_SYSTEM)
            choice = _validate(choice, topics)
            log.info("[selector] LLM chose: %s (%s, %s, %ss)", choice["topic"],
                     choice["niche"], choice["format"], choice["target_seconds"])
            return choice
        except Exception as exc:  # noqa: BLE001
            log.warning("[selector] LLM selection failed (%s) -> heuristic", exc)
    choice = _heuristic(topics)
    log.info("[selector] heuristic chose: %s (%s, %s)", choice["topic"],
             choice["niche"], choice["format"])
    return choice


def _validate(choice: dict, topics: list[Topic]) -> dict:
    allow = _cfg.get("policy.allow_niches", [])
    fmt = _cfg.get("format", {})
    if choice.get("niche") not in allow and allow:
        choice["niche"] = allow[0]
    kind = choice.get("format") if choice.get("format") in ("short", "long") else "short"
    choice["format"] = kind
    bounds = fmt.get(kind, {})
    lo, hi = bounds.get("min_seconds", 20), bounds.get("max_seconds", 59)
    try:
        secs = int(choice.get("target_seconds", lo))
    except (TypeError, ValueError):
        secs = lo
    choice["target_seconds"] = max(lo, min(hi, secs))
    return choice
