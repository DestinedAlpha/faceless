"""Script writer: turn a selection into a scene-by-scene structured script.

The LLM returns hook + scenes (narration, visual direction, image prompt, stock
keywords, on-screen text, sfx, duration) + CTA. Pacing is derived from the target
length (~2.6 spoken words/sec). A template fallback keeps the pipeline runnable
with no LLM key (lower quality, clearly a placeholder).
"""
from __future__ import annotations

from ..core.log import get_logger
from ..llm import client as llm
from .schemas import SCRIPT_SCHEMA

log = get_logger(__name__)

WORDS_PER_SEC = 2.6   # base default; overridden per-playbook (wpm/60)

_SYSTEM = (
    "You are a world-class short-form scriptwriter for a faceless channel. You write "
    "tight, high-retention narration with a scroll-stopping hook, concrete vivid imagery, "
    "and a satisfying payoff. Every scene's image_prompt must be copyright-safe (no real "
    "living celebrities by name in a defamatory way, no logos); prefer evocative, "
    "cinematic, generic-but-specific scenes. Match narration length to the scene duration. "
    "You follow the provided niche PLAYBOOK (structure, pacing, hook style, visual look) "
    "so the script feels native to that format."
)


def _words_per_sec(playbook: dict | None) -> float:
    try:
        return max(2.0, min(3.3, float((playbook or {}).get("voice", {}).get("wpm", 156)) / 60.0))
    except (TypeError, ValueError):
        return WORDS_PER_SEC


def _scene_count(secs: float, playbook: dict | None) -> int:
    pb = playbook or {}
    pacing = pb.get("pacing", {})
    sps = float(pacing.get("seconds_per_scene", 4.5) or 4.5)
    n = round(secs / max(2.0, sps))
    band = pacing.get("scene_count") or [3, 14]
    lo, hi = int(band[0]), int(band[1])
    return max(lo, min(hi, max(3, n)))


def _prompt(selection: dict, playbook: dict | None) -> str:
    secs = selection["target_seconds"]
    kind = selection["format"]
    pb = playbook or {}
    wps = _words_per_sec(pb)
    total_words = int(secs * wps)
    n_scenes = _scene_count(secs, pb)
    per_scene = max(2.0, secs / n_scenes)
    structure = " -> ".join(pb.get("structure", []) or [])
    hooks = "\n".join(f"  - {h}" for h in (pb.get("hook_formulas") or [])[:4])
    visual = pb.get("visual", {})
    art = visual.get("art_direction", selection.get("style", ""))
    consistency = visual.get("consistency", "keep a consistent look across scenes")
    voice_style = pb.get("voice", {}).get("style", selection.get("voice_style", ""))
    return f"""Write a {kind} video script that is native to this niche.

TOPIC: {selection['topic']}
NICHE: {selection['niche']}
HOOK ANGLE: {selection['hook_angle']}

NICHE PLAYBOOK (follow it):
- Beat structure: {structure or 'hook -> build -> payoff -> loop'}
- Narrator delivery: {voice_style}
- Visual art direction (bake into every image_prompt): {art}
- Visual consistency: {consistency}
- Proven hook formulas (use ONE for scene 1):
{hooks or '  - Open with a surprising, specific claim.'}

Constraints:
- Target length ~{secs}s => about {total_words} spoken words total.
- Use about {n_scenes} scenes, each ~{per_scene:.1f}s, roughly following the beat structure.
- Scene 1 narration IS the hook (make it impossible to scroll past) using a hook formula above.
- The final scene should give a satisfying payoff and a loop line that makes scene 1 hit harder.
- image_prompt: a rich text-to-image prompt (subject, setting, lighting, lens, mood) that
  matches the art direction and keeps the subject/look consistent across scenes.
- stock_keywords: 2-4 simple search terms as a B-roll fallback.
- on_screen_text: short punchy caption for that beat (or empty).
- sfx: a short cue like "whoosh", "boom", "riser", or empty.
- duration: your per-scene estimate in seconds (sum ~= {secs}).
Return JSON only, matching the schema."""


def _template(selection: dict, playbook: dict | None) -> dict:
    """No-LLM fallback script (playbook-aware pacing + look)."""
    topic = selection["topic"]
    secs = selection["target_seconds"]
    pb = playbook or {}
    n = _scene_count(secs, pb)
    per = secs / n
    visual = pb.get("visual", {})
    style = visual.get("style_suffix") or selection.get("style", "cinematic")
    sfx_list = pb.get("sfx") or ["whoosh"]
    scenes = []
    for i in range(n):
        if i == 0:
            narration = f"Here's something about {topic} almost nobody knows."
            ost = topic
        elif i == n - 1:
            narration = f"And that's why {topic} still matters today."
            ost = ""
        else:
            narration = f"{topic}: fact number {i}. This part surprises most people."
            ost = ""
        scenes.append({
            "narration": narration,
            "visual_direction": f"Cinematic still illustrating: {topic}",
            "image_prompt": f"{topic}, {style}, dramatic composition, highly detailed",
            "stock_keywords": " ".join(topic.split()[:3]),
            "on_screen_text": ost,
            "sfx": (sfx_list[0] if i == 0
                    else sfx_list[-1] if i == n - 1
                    else sfx_list[i % len(sfx_list)] if i % 2 == 1 else ""),
            "duration": round(per, 1),
        })
    return {
        "title_working": topic,
        "hook": scenes[0]["narration"],
        "scenes": scenes,
        "cta": pb.get("cta", "Follow for more."),
    }


def write_script(selection: dict, playbook: dict | None = None) -> dict:
    if llm.available():
        try:
            script = llm.complete_json(_prompt(selection, playbook), schema=SCRIPT_SCHEMA,
                                       system=_SYSTEM)
            script = _sanitize(script, selection, playbook)
            log.info("[script] LLM wrote %d scenes (~%.0fs)", len(script["scenes"]),
                     sum(s["duration"] for s in script["scenes"]))
            return script
        except Exception as exc:  # noqa: BLE001
            log.warning("[script] LLM script failed (%s) -> template", exc)
    script = _template(selection, playbook)
    log.info("[script] template script with %d scenes", len(script["scenes"]))
    return script


def _sanitize(script: dict, selection: dict, playbook: dict | None = None) -> dict:
    scenes = script.get("scenes") or []
    if not scenes:
        return _template(selection, playbook)
    style_suffix = (playbook or {}).get("visual", {}).get("style_suffix", "")
    for s in scenes:
        s.setdefault("on_screen_text", "")
        s.setdefault("sfx", "")
        s.setdefault("stock_keywords", selection["topic"])
        s.setdefault("image_prompt", f"{selection['topic']}, {selection['style']}")
        # Reinforce the niche's visual look on every image prompt for consistency.
        if style_suffix and style_suffix.lower() not in (s.get("image_prompt") or "").lower():
            s["image_prompt"] = f"{s['image_prompt']}, {style_suffix}"
        try:
            s["duration"] = float(s.get("duration") or 3.0)
        except (TypeError, ValueError):
            s["duration"] = 3.0
        s["duration"] = max(1.5, min(20.0, s["duration"]))
    script.setdefault("hook", scenes[0]["narration"])
    script.setdefault("cta", "Follow for more.")
    script.setdefault("title_working", selection["topic"])
    return script
