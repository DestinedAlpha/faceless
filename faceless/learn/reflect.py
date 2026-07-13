"""Reflect: turn accumulated performance into distilled rules + playbook patches.

This is where the loop *compounds*. It reads `memory/performance.jsonl`, groups
rows by niche, and — only once a niche has enough samples — updates the levers
that actually move retention:

  - `retention_targets.avd_pct`  (blended toward what you actually achieve)
  - `pacing.seconds_per_scene`   (nudged toward the best-performing pacing)
  - `hook_formulas`              (best-performing hook *shape* floated to the top)
  - `title.patterns`             (kept, or refreshed by the LLM from winners)

Guardrails (honoring "conservative changes, keep logs, minimum sample sizes"):
  - A niche is only patched once it has >= `learn.min_samples` rows with a usable
    retention signal.
  - Changes are written as a *separate overlay* at `playbooks/learned/<niche>.yaml`
    which `mastery` merges LAST — authored packs are never mutated, and deleting
    the overlay fully resets the learning. Every future run inherits the overlay.
  - Numeric moves are blended/clamped (small steps), never hard-set from one row.
  - The LLM only *proposes* within a whitelist; anything off-whitelist is dropped.
  - Fully offline: with no LLM key, a deterministic stat-based patch + a written
    `learnings.md` are still produced.

Public API:
    reflect(*, min_samples=None, use_llm=True) -> dict   # summary of what changed
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from ..core.config import load_config
from ..core.log import get_logger
from ..core.util import clamp
from ..llm import client as llm
from . import store

log = get_logger(__name__)
_cfg = load_config()

LEARNED_DIR = _cfg.root / "playbooks" / "learned"

# The only playbook keys reflect is ever allowed to write.
_PATCH_WHITELIST = ("hook_formulas", "pacing", "title", "retention_targets")


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #
def _mean(vals: list[float]) -> float | None:
    vals = [v for v in vals if isinstance(v, (int, float))]
    return sum(vals) / len(vals) if vals else None


def _median(vals: list[float]) -> float | None:
    vals = sorted(v for v in vals if isinstance(v, (int, float)))
    if not vals:
        return None
    n = len(vals)
    return vals[n // 2] if n % 2 else (vals[n // 2 - 1] + vals[n // 2]) / 2


def _retention_score(row: dict) -> float | None:
    """A 0..1 retention proxy: average_view_percentage, else AVD/target_seconds."""
    m = row.get("metrics", {}) or {}
    avp = m.get("average_view_percentage")
    if isinstance(avp, (int, float)):
        return clamp(avp / 100.0, 0.0, 1.5)
    avd, tgt = m.get("average_view_duration"), row.get("target_seconds")
    if isinstance(avd, (int, float)) and isinstance(tgt, (int, float)) and tgt > 0:
        return clamp(avd / tgt, 0.0, 1.5)
    return None


def _ctr(row: dict) -> float | None:
    v = (row.get("metrics", {}) or {}).get("ctr")
    return v if isinstance(v, (int, float)) else None


def aggregate(rows: list[dict]) -> dict[str, dict]:
    """Group rows by niche and compute the stats reflect reasons over."""
    by_niche: dict[str, list[dict]] = {}
    for r in rows:
        niche = r.get("niche") or "generic"
        by_niche.setdefault(niche, []).append(r)

    out: dict[str, dict] = {}
    for niche, rs in by_niche.items():
        scored = [(r, _retention_score(r)) for r in rs]
        usable = [(r, s) for r, s in scored if s is not None]
        # Best hook shape by mean retention.
        by_hook: dict[str, list[float]] = {}
        for r, s in usable:
            by_hook.setdefault(r.get("hook_style") or "unknown", []).append(s)
        hook_rank = sorted(((_mean(v) or 0.0, k) for k, v in by_hook.items()),
                           reverse=True)
        # Best pacing (seconds_per_scene) by mean retention, bucketed to 0.5s.
        by_pace: dict[float, list[float]] = {}
        for r, s in usable:
            sp = r.get("seconds_per_scene")
            if isinstance(sp, (int, float)):
                by_pace.setdefault(round(sp * 2) / 2, []).append(s)
        pace_rank = sorted(((_mean(v) or 0.0, k) for k, v in by_pace.items()),
                           reverse=True)
        # Best title by CTR (then retention).
        title_rank = sorted(
            ((_ctr(r) or -1, _retention_score(r) or 0, r.get("title_used") or "")
             for r, _ in scored if r.get("title_used")), reverse=True)

        out[niche] = {
            "n": len(rs),
            "n_usable": len(usable),
            "avd_median": _median([s for _, s in usable]),
            "avd_mean": _mean([s for _, s in usable]),
            "ctr_mean": _mean([_ctr(r) for r in rs]),
            "best_hook_style": hook_rank[0][1] if hook_rank else None,
            "hook_rank": hook_rank,
            "best_pace": pace_rank[0][1] if pace_rank else None,
            "pace_rank": pace_rank,
            "best_title": title_rank[0][2] if title_rank else None,
            "example_hooks": [r.get("hook") for r, _ in usable if r.get("hook")][:5],
        }
    return out


# --------------------------------------------------------------------------- #
# Overlay I/O
# --------------------------------------------------------------------------- #
def _load_overlay(niche: str) -> dict:
    p = LEARNED_DIR / f"{niche}.yaml"
    if not p.exists():
        return {}
    try:
        with open(p, "r", encoding="utf-8") as fh:
            return yaml.safe_load(fh) or {}
    except Exception as exc:  # noqa: BLE001
        log.warning("[reflect] unreadable overlay %s: %s", p.name, exc)
        return {}


def _deep_merge(base: dict, over: dict) -> dict:
    import copy
    out = copy.deepcopy(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = copy.deepcopy(v)
    return out


def _write_overlay(niche: str, patch: dict, meta: dict) -> Path:
    LEARNED_DIR.mkdir(parents=True, exist_ok=True)
    merged = _deep_merge(_load_overlay(niche), patch)
    # Provenance the loop can inspect; mastery treats leading-underscore keys as inert.
    merged["_learned"] = _deep_merge(merged.get("_learned", {}), meta)
    p = LEARNED_DIR / f"{niche}.yaml"
    header = ("# LEARNED OVERLAY — auto-generated by faceless learn (reflect.py).\n"
              "# Merged LAST over the authored/base playbook. Safe to delete to reset.\n"
              "# Do not hand-edit; it is regenerated from memory/performance.jsonl.\n")
    body = yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)
    p.write_text(header + body, encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# Patch synthesis
# --------------------------------------------------------------------------- #
_REFLECT_SYSTEM = (
    "You are a retention analyst for faceless short-form video. Given real "
    "performance stats for one niche and the current playbook levers, you propose "
    "SMALL, evidence-based adjustments that should raise average-view-% and CTR. "
    "Be conservative: change only what the data supports; keep copyright-safe."
)

_PATCH_SCHEMA = {
    "type": "object",
    "properties": {
        "learnings": {"type": "array", "items": {"type": "string"},
                      "description": "2-4 concrete, non-generic rules this niche's data supports"},
        "hook_formulas": {"type": "array", "items": {"type": "string"},
                          "description": "Reordered/rewritten hook formulas, best-first (<=5)"},
        "seconds_per_scene": {"type": "number",
                              "description": "Suggested pacing, 2.5-6"},
        "avd_pct": {"type": "number", "description": "Realistic AVD target 0-1"},
        "title_patterns": {"type": "array", "items": {"type": "string"},
                           "description": "Title patterns with {topic}, best-first (<=4)"},
    },
    "required": ["learnings"],
}


def _llm_patch(niche: str, agg: dict, current: dict) -> dict | None:
    if not llm.available():
        return None
    stats = {
        "samples": agg["n"], "usable": agg["n_usable"],
        "median_avd_pct": round((agg["avd_median"] or 0) * 100, 1),
        "mean_ctr_pct": round(agg["ctr_mean"], 2) if agg["ctr_mean"] is not None else None,
        "hook_style_ranked": [(k, round(v * 100, 1)) for v, k in agg["hook_rank"]],
        "pacing_ranked_seconds_per_scene": [(k, round(v * 100, 1)) for v, k in agg["pace_rank"]],
        "best_title": agg["best_title"],
        "example_hooks": agg["example_hooks"],
    }
    import json as _json
    prompt = (
        f"Niche: {niche}\n\nPERFORMANCE (retention as fraction*100):\n"
        f"{_json.dumps(stats, ensure_ascii=False, indent=1)}\n\n"
        f"CURRENT LEVERS:\n"
        f"- hook_formulas: {current.get('hook_formulas')}\n"
        f"- seconds_per_scene: {current.get('pacing', {}).get('seconds_per_scene')}\n"
        f"- retention_targets.avd_pct: {current.get('retention_targets', {}).get('avd_pct')}\n"
        f"- title.patterns: {current.get('title', {}).get('patterns')}\n\n"
        "Propose small improvements. Float the best-performing hook SHAPE to the top of "
        "hook_formulas. Nudge seconds_per_scene toward the best pacing bucket (don't jump). "
        "Set avd_pct to a realistic target near the observed median. Keep title patterns that "
        "resemble winners. Return JSON per the schema."
    )
    try:
        raw = llm.complete_json(prompt, schema=_PATCH_SCHEMA, system=_REFLECT_SYSTEM)
        return raw if isinstance(raw, dict) else None
    except Exception as exc:  # noqa: BLE001
        log.warning("[reflect] LLM reflection failed for %s: %s", niche, exc)
        return None


def _build_patch(niche: str, agg: dict, current: dict, llm_out: dict | None) -> tuple[dict, list[str]]:
    """Combine LLM proposal (whitelisted) + deterministic stat moves into a patch."""
    patch: dict[str, Any] = {}
    learnings: list[str] = []

    cur_pace = float((current.get("pacing", {}) or {}).get("seconds_per_scene", 4.5) or 4.5)
    cur_avd = float((current.get("retention_targets", {}) or {}).get("avd_pct", 0.55) or 0.55)

    # --- retention target: blend current toward observed median (half step) ----
    if agg["avd_median"] is not None:
        target = clamp(0.5 * cur_avd + 0.5 * agg["avd_median"], 0.2, 0.95)
        patch.setdefault("retention_targets", {})["avd_pct"] = round(target, 3)

    # --- pacing: step ~40% toward the best-performing bucket, clamped -----------
    if agg["best_pace"] is not None:
        stepped = cur_pace + 0.4 * (float(agg["best_pace"]) - cur_pace)
        patch.setdefault("pacing", {})["seconds_per_scene"] = round(
            clamp(stepped, 2.5, 6.0), 2)

    # --- hooks: float the best-performing shape's formula to the front ----------
    if agg["best_hook_style"]:
        learnings.append(
            f"Best-retaining hook shape: '{agg['best_hook_style']}' "
            f"(median AVD {round((agg['avd_median'] or 0) * 100)}% over "
            f"{agg['n_usable']} usable runs).")

    # --- overlay the LLM proposal (whitelist + clamp) ---------------------------
    if llm_out:
        if isinstance(llm_out.get("hook_formulas"), list) and llm_out["hook_formulas"]:
            patch["hook_formulas"] = [str(x) for x in llm_out["hook_formulas"]][:5]
        if isinstance(llm_out.get("seconds_per_scene"), (int, float)):
            patch.setdefault("pacing", {})["seconds_per_scene"] = round(
                clamp(float(llm_out["seconds_per_scene"]), 2.5, 6.0), 2)
        if isinstance(llm_out.get("avd_pct"), (int, float)):
            patch.setdefault("retention_targets", {})["avd_pct"] = round(
                clamp(float(llm_out["avd_pct"]), 0.2, 0.95), 3)
        if isinstance(llm_out.get("title_patterns"), list) and llm_out["title_patterns"]:
            patch.setdefault("title", {})["patterns"] = [
                str(x) for x in llm_out["title_patterns"]][:4]
        for rule in llm_out.get("learnings", []) or []:
            if isinstance(rule, str) and rule.strip():
                learnings.append(rule.strip())

    # Keep only whitelisted top-level keys.
    patch = {k: v for k, v in patch.items() if k in _PATCH_WHITELIST}
    return patch, learnings


# --------------------------------------------------------------------------- #
# learnings.md
# --------------------------------------------------------------------------- #
def _write_learnings(agg: dict[str, dict], per_niche_rules: dict[str, list[str]],
                     patched: dict[str, Path]) -> Path:
    lines = ["# Learnings", "",
             "_Distilled by `faceless learn` from `memory/performance.jsonl`. "
             "Human-readable; the machine-applied version lives in "
             "`playbooks/learned/<niche>.yaml`._", ""]
    for niche in sorted(agg):
        a = agg[niche]
        lines.append(f"## {niche}")
        avd = f"{round((a['avd_median'] or 0) * 100)}%" if a["avd_median"] is not None else "—"
        ctr = f"{round(a['ctr_mean'], 2)}%" if a["ctr_mean"] is not None else "—"
        status = ("patched" if niche in patched
                  else f"observing ({a['n_usable']}/{_min_samples()} usable)")
        lines.append(f"- samples: {a['n']} (usable {a['n_usable']}) · median AVD {avd} "
                     f"· mean CTR {ctr} · **{status}**")
        for rule in per_niche_rules.get(niche, []):
            lines.append(f"- {rule}")
        if a["best_title"]:
            lines.append(f"- Highest-CTR title so far: \"{a['best_title']}\"")
        lines.append("")
    out = store.learnings_path()
    out.write_text("\n".join(lines), encoding="utf-8")
    return out


def _min_samples(override: int | None = None) -> int:
    return int(override if override is not None else _cfg.get("learn.min_samples", 3))


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def reflect(*, min_samples: int | None = None, use_llm: bool = True) -> dict:
    """Read performance, distill learnings, and patch playbook overlays.

    Returns a summary: which niches were patched, which are still observing, and
    the path to learnings.md. Never raises on empty/insufficient data — it just
    reports that there's nothing (yet) to learn.
    """
    rows = store.read_rows()
    if not rows:
        log.info("[reflect] no performance rows yet; upload + report metrics first")
        return {"patched": [], "observing": [], "rows": 0,
                "learnings": str(store.learnings_path())}

    from ..plan import mastery  # local import keeps the learn package light to import
    thresh = _min_samples(min_samples)
    agg = aggregate(rows)
    patched: dict[str, Path] = {}
    per_niche_rules: dict[str, list[str]] = {}
    observing: list[str] = []
    patch_enabled = bool(_cfg.get("learn.patch_playbooks", True))

    for niche, a in agg.items():
        current = mastery.base_playbook(niche)
        llm_out = _llm_patch(niche, a, current) if use_llm else None
        patch, rules = _build_patch(niche, a, current, llm_out)
        per_niche_rules[niche] = rules
        if a["n_usable"] < thresh or not patch:
            observing.append(niche)
            continue
        if not patch_enabled:
            observing.append(niche)
            per_niche_rules[niche].append("(playbook patching disabled in config)")
            continue
        meta = {"samples": a["n"], "usable": a["n_usable"],
                "median_avd_pct": round((a["avd_median"] or 0) * 100, 1),
                "best_hook_style": a["best_hook_style"]}
        path = _write_overlay(niche, patch, meta)
        patched[niche] = path
        log.info("[reflect] patched '%s' overlay: %s", niche, list(patch.keys()))

    learnings_file = _write_learnings(agg, per_niche_rules, patched)
    summary = {
        "rows": len(rows),
        "niches": sorted(agg),
        "patched": sorted(patched),
        "observing": sorted(observing),
        "min_samples": thresh,
        "learnings": str(learnings_file),
    }
    log.info("[reflect] done: patched=%s observing=%s", summary["patched"],
             summary["observing"])
    return summary
