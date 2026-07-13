"""Quality gate: catch weak or unsafe scripts before we spend a render on them.

Two gates:

  * `gate(script, selection, playbook)` — PRE-render. Scores the script on hook
    strength, pacing sanity (scene count + durations within the playbook's bands),
    coherence (every beat carries narration + a consistent look), and content policy
    (no blocked terms). Policy is a hard fail. If the weighted score is below the
    configured threshold and an LLM is available, it asks the model for ONE targeted
    revision of the weak parts and keeps whichever version scores higher. Returns the
    (possibly revised) script plus a structured report for the review folder.

  * `post_render_check(spec, scene_audio, out_mp4)` — POST-render. Cheap sanity: the
    file exists and isn't tiny, the rendered duration matches the spec within
    tolerance, and every scene actually has audio. Never raises; returns a report.

Everything degrades: with no LLM, the gate still scores + reports (it just can't
auto-revise), and the pipeline decides what to do with a soft fail (log + ship).

Public API:
    gate(script, selection, playbook) -> (script, report)
    post_render_check(spec, scene_audio, out_mp4) -> report
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

from ..core.config import load_config
from ..core.log import get_logger
from ..llm import client as llm
from .schemas import SCRIPT_SCHEMA

log = get_logger(__name__)
_cfg = load_config()

# Generic filler openers that signal a weak, templated hook.
_WEAK_HOOK_MARKERS = (
    "here's something", "did you know", "in this video", "today we", "let's talk about",
    "have you ever", "welcome", "this is a story about",
)


# --------------------------------------------------------------------------- #
# Pre-render scoring
# --------------------------------------------------------------------------- #
def _band(pb: dict, *keys, default=None):
    node = pb or {}
    for k in keys:
        if not isinstance(node, dict):
            return default
        node = node.get(k)
    return node if node is not None else default


def _hook_score(script: dict, min_words: int) -> tuple[float, list[str]]:
    issues: list[str] = []
    hook = (script.get("hook") or "").strip()
    words = hook.split()
    if not hook:
        return 0.0, ["hook is empty"]
    score = 1.0
    if len(words) < min_words:
        score -= 0.5
        issues.append(f"hook is only {len(words)} words (min {min_words})")
    if len(words) > 22:
        score -= 0.2
        issues.append("hook is too long to land in the first ~2s")
    low = hook.lower()
    if any(low.startswith(m) or m in low for m in _WEAK_HOOK_MARKERS):
        score -= 0.4
        issues.append("hook opens with a generic filler phrase")
    if not any(ch.isdigit() for ch in hook) and "?" not in hook and len(words) < 8:
        score -= 0.1  # neither a concrete number nor a question nor a full statement
    return max(0.0, score), issues


def _pacing_score(script: dict, selection: dict, playbook: dict) -> tuple[float, list[str]]:
    issues: list[str] = []
    scenes = script.get("scenes") or []
    n = len(scenes)
    score = 1.0
    band = _band(playbook, "pacing", "scene_count", default=[3, 14]) or [3, 14]
    lo, hi = int(band[0]), int(band[1])
    if n < lo:
        score -= 0.4
        issues.append(f"only {n} scenes (playbook wants >= {lo})")
    elif n > hi:
        score -= 0.25
        issues.append(f"{n} scenes (playbook caps at {hi})")

    durs = [float(s.get("duration") or 0) for s in scenes]
    total = sum(durs)
    tband = _band(playbook, "pacing", "total_seconds", default=None)
    target = float(selection.get("target_seconds", total or 40))
    if tband and total:
        tlo, thi = float(tband[0]), float(tband[1])
        if not (tlo * 0.7 <= total <= thi * 1.3):
            score -= 0.2
            issues.append(f"total ~{total:.0f}s outside pacing band {tband}")
    elif total and abs(total - target) / max(target, 1) > 0.4:
        score -= 0.2
        issues.append(f"total ~{total:.0f}s far from target {target:.0f}s")

    long_scenes = [i for i, d in enumerate(durs) if d > 9.0]
    if long_scenes:
        score -= 0.15
        issues.append(f"scene(s) {long_scenes} run long (>9s) — risk of a dead beat")
    return max(0.0, score), issues


def _coherence_score(script: dict, min_scene_words: int) -> tuple[float, list[str]]:
    issues: list[str] = []
    scenes = script.get("scenes") or []
    if not scenes:
        return 0.0, ["no scenes"]
    score = 1.0
    seen: set[str] = set()
    dead = []
    for i, s in enumerate(scenes):
        narr = (s.get("narration") or "").strip()
        if i != len(scenes) - 1 and len(narr.split()) < min_scene_words:
            dead.append(i)
        key = narr.lower()
        if key and key in seen:
            score -= 0.2
            issues.append(f"scene {i} narration duplicates an earlier beat")
        seen.add(key)
        if not (s.get("image_prompt") or "").strip():
            score -= 0.1
            issues.append(f"scene {i} has no image_prompt")
    if dead:
        score -= min(0.5, 0.15 * len(dead))
        issues.append(f"flat/dead beat(s) at scene(s) {dead} (too few words)")
    return max(0.0, score), issues


def _policy_hits(script: dict, selection: dict) -> list[str]:
    blocked = [b.lower() for b in _cfg.get("policy.blocked_terms", []) if b]
    if not blocked:
        return []
    hay = " ".join([
        selection.get("topic", ""), script.get("title_working", ""), script.get("hook", ""),
        *[s.get("narration", "") for s in script.get("scenes") or []],
        *[s.get("on_screen_text", "") for s in script.get("scenes") or []],
        *[s.get("image_prompt", "") for s in script.get("scenes") or []],
    ]).lower()
    return sorted({b for b in blocked if b in hay})


def check(script: dict, selection: dict, playbook: dict | None) -> dict:
    """Score a script; return a structured report (no side effects)."""
    pb = playbook or {}
    min_hook_words = int(_cfg.get("qc.min_hook_words", 4))
    min_scene_words = int(_cfg.get("qc.min_scene_words", 3))

    hook_s, hook_i = _hook_score(script, min_hook_words)
    pace_s, pace_i = _pacing_score(script, selection, pb)
    coh_s, coh_i = _coherence_score(script, min_scene_words)
    policy = _policy_hits(script, selection)

    # Hook is the dominant retention lever, so it carries the most weight.
    score = round(0.45 * hook_s + 0.30 * pace_s + 0.25 * coh_s, 3)
    threshold = float(_cfg.get("qc.min_score", 0.62))
    passed = score >= threshold and not policy

    return {
        "score": score,
        "threshold": threshold,
        "passed": passed,
        "policy_violations": policy,
        "checks": {
            "hook": {"score": round(hook_s, 3), "issues": hook_i},
            "pacing": {"score": round(pace_s, 3), "issues": pace_i},
            "coherence": {"score": round(coh_s, 3), "issues": coh_i},
        },
        "issues": hook_i + pace_i + coh_i
                  + ([f"POLICY: blocked term(s) present: {policy}"] if policy else []),
    }


# --------------------------------------------------------------------------- #
# Revision
# --------------------------------------------------------------------------- #
_REVISE_SYSTEM = (
    "You are a script doctor for high-retention short-form video. You are given a "
    "script and a list of concrete problems from a quality gate. You return a fixed "
    "version of the SAME script (same topic, same scene count where possible) that "
    "resolves every listed issue — especially a weak hook and any flat/dead beats — "
    "while keeping it copyright-safe (no blocked terms, no logos, no defamatory real "
    "names). Keep each scene's fields intact. Return JSON only."
)


def _revise(script: dict, selection: dict, playbook: dict | None, report: dict) -> dict | None:
    if not llm.available():
        return None
    from . import script as script_mod  # reuse the same sanitizer/pacing rules
    import json
    issues = report.get("issues") or []
    prompt = (
        f"TOPIC: {selection['topic']}\nNICHE: {selection['niche']}\n\n"
        "Fix these quality-gate problems in the script below:\n- "
        + "\n- ".join(issues) + "\n\n"
        "Rewrite ONLY what's needed to fix them (usually the hook and any flat beat), "
        "keep everything else. Here is the current script JSON:\n"
        + json.dumps({"title_working": script.get("title_working"),
                      "hook": script.get("hook"),
                      "scenes": script.get("scenes"),
                      "cta": script.get("cta")}, ensure_ascii=False)
        + "\n\nReturn the corrected script as JSON matching the schema."
    )
    try:
        revised = llm.complete_json(prompt, schema=SCRIPT_SCHEMA, system=_REVISE_SYSTEM)
        return script_mod._sanitize(revised, selection, playbook)
    except Exception as exc:  # noqa: BLE001
        log.warning("[qc] revision failed (%s)", exc)
        return None


def gate(script: dict, selection: dict, playbook: dict | None = None) -> tuple[dict, dict]:
    """Pre-render gate. Returns (script_to_use, report). May auto-revise once."""
    if not _cfg.get("qc.enabled", True):
        rep = check(script, selection, playbook)
        rep["skipped"] = True
        return script, rep

    report = check(script, selection, playbook)
    log.info("[qc] pre-render score %.2f (threshold %.2f) — %s", report["score"],
             report["threshold"], "PASS" if report["passed"] else "FAIL")

    if not report["passed"] and _cfg.get("qc.revise", True):
        for issue in report["issues"]:
            log.info("[qc]   issue: %s", issue)
        revised = _revise(script, selection, playbook, report)
        if revised is not None:
            rep2 = check(revised, selection, playbook)
            log.info("[qc] post-revision score %.2f — %s", rep2["score"],
                     "PASS" if rep2["passed"] else "still below threshold")
            if rep2["score"] >= report["score"]:
                rep2["revised"] = True
                rep2["previous_score"] = report["score"]
                return revised, rep2
    report["revised"] = False
    return script, report


# --------------------------------------------------------------------------- #
# Post-render sanity
# --------------------------------------------------------------------------- #
def _ffprobe_duration(path: Path) -> float | None:
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    try:
        out = subprocess.run(
            [exe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
            capture_output=True, text=True, timeout=30, shell=False,
        )
        return float(out.stdout.strip())
    except (ValueError, subprocess.SubprocessError, OSError):
        return None


def post_render_check(spec: dict, scene_audio: list[dict],
                      out_mp4: str | Path | None) -> dict:
    """Cheap post-render sanity. Never raises; returns a report dict."""
    issues: list[str] = []
    checks: dict[str, bool] = {}

    path = Path(out_mp4) if out_mp4 else None
    exists = bool(path and path.exists())
    checks["file_exists"] = exists
    if not exists:
        issues.append("rendered mp4 is missing")
    else:
        size = path.stat().st_size
        checks["file_nontrivial"] = size > 10_240
        if size <= 10_240:
            issues.append(f"rendered mp4 is suspiciously small ({size} bytes)")

    # Duration matches the spec within tolerance.
    fps = float(spec.get("meta", {}).get("fps", 30)) or 30
    spec_secs = float(spec.get("meta", {}).get("durationInFrames", 0)) / fps
    if exists and spec_secs > 0:
        actual = _ffprobe_duration(path)
        if actual is None:
            checks["duration_match"] = True  # can't probe (no ffprobe) -> don't fail
        else:
            tol = float(_cfg.get("qc.duration_tolerance", 0.15))
            ok = abs(actual - spec_secs) <= tol * spec_secs
            checks["duration_match"] = ok
            if not ok:
                issues.append(f"rendered {actual:.1f}s vs spec {spec_secs:.1f}s "
                              f"(> {tol:.0%} off)")

    # Every scene produced real audio.
    silent = [sa.get("index", i) for i, sa in enumerate(scene_audio)
              if float(sa.get("duration") or 0) <= 0.05]
    checks["audio_present"] = not silent
    if silent:
        issues.append(f"scene(s) {silent} have no audio")

    report = {"passed": not issues, "checks": checks, "issues": issues}
    log.info("[qc] post-render %s%s", "PASS" if report["passed"] else "FAIL",
             "" if report["passed"] else f" — {issues}")
    return report
