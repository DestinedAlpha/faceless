"""Hook lab: generate several candidate opening lines, self-score them, pick the best.

The hook is the single highest-leverage retention lever, so we don't trust the
first line the scriptwriter produces. Instead we ask the LLM for N candidate hooks
shaped by the niche playbook's `hook_formulas`, have it score each on curiosity,
specificity, stakes and raw scroll-stop power, then pick the strongest (and keep a
runner-up for A/B). Every candidate + score is logged to `hooks.json` so the future
learn loop can validate which hook *shapes* actually held attention.

Degrades gracefully: with no LLM key we return the script's own hook as the single
candidate, so the pipeline still runs and nothing downstream changes shape.

Public API:
    develop_hooks(selection, playbook, script=None, n=5) -> dict
        -> {"winner": str, "alt": str|None, "candidates": [ {hook, ...scores, total} ]}
"""
from __future__ import annotations

from ..core.log import get_logger
from ..llm import client as llm
from .schemas import HOOK_LAB_SCHEMA

log = get_logger(__name__)

# Weighting of the four self-scored axes. Scroll-stop and curiosity matter most for
# the first frame; specificity and stakes keep the promise credible.
_WEIGHTS = {"scroll_stop": 0.35, "curiosity": 0.30, "specificity": 0.20, "stakes": 0.15}

_SYSTEM = (
    "You are a short-form hook specialist. You write opening lines that make it "
    "physically hard to scroll past, then judge them honestly. A great hook opens a "
    "curiosity loop, is concrete and specific (real numbers, vivid nouns), raises "
    "clear stakes, and fits how people actually talk. It is copyright-safe (no real "
    "named living person in a defamatory way, no logos) and never clickbait it can't "
    "pay off. You always return valid JSON."
)


def _score(cand: dict) -> float:
    total = 0.0
    for axis, w in _WEIGHTS.items():
        try:
            v = float(cand.get(axis, 0))
        except (TypeError, ValueError):
            v = 0.0
        total += w * max(0.0, min(10.0, v))
    return round(total, 3)


def _prompt(selection: dict, playbook: dict | None, script: dict | None, n: int) -> str:
    pb = playbook or {}
    formulas = "\n".join(f"  - {h}" for h in (pb.get("hook_formulas") or [])[:6])
    voice = pb.get("voice", {}).get("style", selection.get("voice_style", ""))
    seed_hook = (script or {}).get("hook", "")
    seed = f"\nThe current draft hook (beat it or confirm it's already best):\n  \"{seed_hook}\"\n" if seed_hook else ""
    return f"""Write {n} DISTINCT candidate opening lines (the first spoken sentence) for this video.

TOPIC: {selection['topic']}
NICHE: {selection['niche']}
HOOK ANGLE: {selection['hook_angle']}
NARRATOR DELIVERY: {voice}
{seed}
Use a DIFFERENT proven hook formula for each candidate where possible:
{formulas or '  - Open with a surprising, specific claim.'}

For EACH candidate:
- hook: one spoken line, <=18 words, no emoji, no hashtags, no quotes around it.
- Then honestly score it 1-10 on curiosity, specificity, stakes, scroll_stop.
- rationale: one short line on why it works and which formula it uses.

Make the candidates genuinely varied in angle (don't reword one idea {n} times).
Return JSON only, matching the schema."""


def _from_llm(selection: dict, playbook: dict | None, script: dict | None, n: int) -> list[dict] | None:
    try:
        raw = llm.complete_json(_prompt(selection, playbook, script, n),
                                schema=HOOK_LAB_SCHEMA, system=_SYSTEM)
    except Exception as exc:  # noqa: BLE001
        log.warning("[hook_lab] LLM hook generation failed (%s)", exc)
        return None
    cands = (raw or {}).get("candidates") if isinstance(raw, dict) else None
    if not cands:
        return None
    out: list[dict] = []
    seen: set[str] = set()
    for c in cands:
        hook = (c.get("hook") or "").strip().strip('"').strip()
        key = hook.lower()
        if not hook or key in seen:
            continue
        seen.add(key)
        c["hook"] = hook
        c["total"] = _score(c)
        out.append(c)
    return out or None


def _fallback(selection: dict, playbook: dict | None, script: dict | None) -> list[dict]:
    """No-LLM path: use whatever hook the script/template already has, unscored."""
    hook = ((script or {}).get("hook")
            or f"Here's something about {selection['topic']} almost nobody knows.")
    return [{
        "hook": hook.strip(),
        "curiosity": 0, "specificity": 0, "stakes": 0, "scroll_stop": 0,
        "rationale": "fallback: no LLM available; kept the draft hook.",
        "total": 0.0,
    }]


def develop_hooks(selection: dict, playbook: dict | None = None,
                  script: dict | None = None, n: int = 5) -> dict:
    """Generate, score and rank candidate hooks; return the winner + an A/B alt.

    Always returns a usable dict, even offline. `candidates` is the full ranked log.
    """
    n = max(2, min(8, int(n)))
    cands = _from_llm(selection, playbook, script, n) if llm.available() else None
    if not cands:
        cands = _fallback(selection, playbook, script)

    cands.sort(key=lambda c: c.get("total", 0.0), reverse=True)
    winner = cands[0]["hook"]
    alt = cands[1]["hook"] if len(cands) > 1 else None
    log.info("[hook_lab] %d candidate(s); winner (score %.2f): %s",
             len(cands), cands[0].get("total", 0.0), winner)
    return {"winner": winner, "alt": alt, "candidates": cands}
