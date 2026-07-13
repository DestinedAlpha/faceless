"""YouTube metadata: clickable title (+A/B variants), description, tags, thumbnail text.

The LLM turns the finished script into packaging that maximizes click-through while
staying honest to the content. It is steered by the niche playbook's title/headline
patterns and thumbnail style, produces 2-3 **A/B title variants** (and thumbnail-text
variants) so you can test what earns the click, and — for long-form — a chapter list.
Falls back to a plain template built from the script + playbook patterns when no LLM
key is present, so the pipeline still produces valid metadata offline.
"""
from __future__ import annotations

from ..core.log import get_logger
from ..llm import client as llm
from ..plan.schemas import METADATA_SCHEMA

log = get_logger(__name__)

_SYSTEM = (
    "You are a YouTube growth specialist. You write titles that earn the click without "
    "lying (curiosity gap, stakes, specificity), descriptions that front-load the hook "
    "and include a few relevant hashtags, and tight tag lists. You give 2-3 genuinely "
    "different A/B title options (different angle each — question vs number vs bold "
    "claim), and 2-3 thumbnail-text options. Thumbnail text is 3-5 punchy words. Keep "
    "everything brand-safe and copyright-safe."
)


def _mmss(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    return f"{seconds // 60:02d}:{seconds % 60:02d}"


def _derive_chapters(script: dict) -> list[dict]:
    """Build YouTube chapter markers from the script's beats when the LLM gave none.

    Long-form needs ≥3 chapters and the first at 00:00. We walk the scenes by their
    estimated durations, grouping them into ~5 evenly-sized chapters, and label each
    from its first beat's on-screen text (or a trimmed narration). Purely a fallback
    so long-form always ships valid chapters even offline / when the model omits them.
    """
    scenes = script.get("scenes") or []
    if len(scenes) < 3:
        return []
    # Cumulative start time (seconds) of each scene from its duration estimate.
    starts, t = [], 0.0
    for s in scenes:
        starts.append(t)
        try:
            t += float(s.get("duration") or 4.0)
        except (TypeError, ValueError):
            t += 4.0
    target = min(6, max(3, len(scenes) // 3))     # aim for 3-6 chapters
    step = max(1, len(scenes) // target)
    out: list[dict] = []
    for i in range(0, len(scenes), step):
        s = scenes[i]
        label = (s.get("on_screen_text") or "").strip() or \
                " ".join((s.get("narration") or "").split()[:6]).strip() or f"Part {len(out) + 1}"
        out.append({"time": _mmss(starts[i]), "label": label[:60]})
        if len(out) >= target:
            break
    if out:
        out[0]["time"] = "00:00"                  # YouTube requires the first at 00:00
    return out


def _fill_patterns(patterns: list, topic: str) -> list[str]:
    """Render playbook title.patterns like 'The truth about {topic}' -> concrete titles."""
    out: list[str] = []
    for p in patterns or []:
        try:
            out.append(str(p).format(topic=topic)[:100])
        except (KeyError, IndexError, ValueError):
            out.append(str(p)[:100])
    return out


def _prompt(selection: dict, script: dict, playbook: dict | None) -> str:
    pb = playbook or {}
    narration = " ".join(s.get("narration", "") for s in script.get("scenes", []))
    is_long = selection["format"] != "short"
    patterns = "\n".join(f"  - {p}" for p in (pb.get("title", {}).get("patterns") or [])[:5])
    thumb_style = pb.get("thumbnail", {}).get("style", "high-contrast, bold, subject-forward")
    chapters_line = ("- chapters: 3-6 markers, first at 00:00, labels tied to the beats."
                     if is_long else
                     "- chapters: return an empty array (this is a Short).")
    return f"""Package this finished video for YouTube.

NICHE: {selection['niche']}
FORMAT: {selection['format']}  (a {'long-form video' if is_long else 'Short'})
WORKING TITLE: {script.get('title_working', selection['topic'])}
HOOK: {script.get('hook', '')}
FULL NARRATION: {narration[:1500]}

This niche's proven title/headline patterns (adapt them, don't copy blindly):
{patterns or '  - The truth about {topic}'}
This niche's thumbnail style: {thumb_style}

Return JSON only:
- title: the single strongest option, <=100 chars, no clickbait lies.
- title_variants: 2-3 DISTINCT A/B options (include `title`), each a different angle.
- description: 2-4 sentences, hook first, end with 3-5 relevant #hashtags.
- tags: 8-15 lowercase search tags (use the real topic keywords).
- thumbnail_text: 3-5 words, high-contrast punch.
- thumbnail_variants: 2-3 DISTINCT 3-5 word thumbnail options.
- thumbnail_prompt: a vivid text-to-image prompt for the thumbnail background
  (cinematic, high-contrast, leaves room for the text; copyright-safe).
{chapters_line}"""


def _template(selection: dict, script: dict, playbook: dict | None) -> dict:
    topic = script.get("title_working", selection["topic"])
    pb = playbook or {}
    patterns = _fill_patterns(pb.get("title", {}).get("patterns"), topic)
    variants = list(dict.fromkeys([topic[:100], *patterns]))[:3]
    return {
        "title": variants[0],
        "title_variants": variants,
        "description": (f"{script.get('hook', topic)}\n\n"
                        f"#shorts #{selection['niche'].replace('-', '')} #facts"),
        "tags": list(dict.fromkeys(
            [selection["niche"], "facts", "shorts", "didyouknow"]
            + [w.lower() for w in topic.split() if len(w) > 3][:8]
        )),
        "thumbnail_text": " ".join(topic.split()[:4]).upper(),
        "thumbnail_variants": [" ".join(topic.split()[:4]).upper()],
        "thumbnail_prompt": f"{topic}, {selection.get('style', 'cinematic')}, "
                            "dramatic high-contrast lighting, bold composition",
        "chapters": [] if selection["format"] == "short" else _derive_chapters(script),
    }


def _sanitize(md: dict, selection: dict, script: dict, playbook: dict | None) -> dict:
    tmpl = _template(selection, script, playbook)
    for key in ("title", "description", "thumbnail_text", "thumbnail_prompt"):
        if not md.get(key):
            md[key] = tmpl[key]
    md["title"] = str(md["title"])[:100]

    # Title A/B variants: dedupe, cap length/count, always include the primary title.
    variants = md.get("title_variants")
    if not isinstance(variants, list) or not variants:
        variants = tmpl["title_variants"]
    variants = [str(v)[:100] for v in variants if str(v).strip()]
    if md["title"] not in variants:
        variants = [md["title"], *variants]
    md["title_variants"] = list(dict.fromkeys(variants))[:3]

    # Thumbnail text variants.
    tvars = md.get("thumbnail_variants")
    if not isinstance(tvars, list) or not tvars:
        tvars = [md["thumbnail_text"]]
    tvars = [str(v).strip() for v in tvars if str(v).strip()]
    if md["thumbnail_text"] not in tvars:
        tvars = [md["thumbnail_text"], *tvars]
    md["thumbnail_variants"] = list(dict.fromkeys(tvars))[:3]

    tags = md.get("tags")
    md["tags"] = ([str(t)[:40] for t in tags][:15]
                  if isinstance(tags, list) and tags else tmpl["tags"])

    # Chapters only make sense for long-form; drop for Shorts.
    if selection["format"] == "short":
        md["chapters"] = []
    else:
        ch = md.get("chapters")
        ch = [c for c in ch if isinstance(c, dict) and c.get("time") and c.get("label")] \
            if isinstance(ch, list) else []
        # YouTube needs ≥3 markers with the first at 00:00 to render chapters. If the
        # LLM under-delivered, derive them from the script's beats so long-form always
        # ships usable chapters.
        if len(ch) < 3:
            ch = _derive_chapters(script) or ch
        if ch:
            ch[0]["time"] = "00:00"
        md["chapters"] = ch
    return md


def generate(selection: dict, script: dict, playbook: dict | None = None) -> dict:
    if llm.available():
        try:
            md = llm.complete_json(_prompt(selection, script, playbook),
                                   schema=METADATA_SCHEMA, system=_SYSTEM)
            md = _sanitize(md, selection, script, playbook)
            log.info("[metadata] LLM title: %s (%d A/B variant(s))",
                     md["title"], len(md["title_variants"]))
            return md
        except Exception as exc:  # noqa: BLE001
            log.warning("[metadata] LLM failed (%s) -> template", exc)
    md = _template(selection, script, playbook)
    log.info("[metadata] template title: %s", md["title"])
    return md
