"""YouTube metadata: clickable title, description, tags, thumbnail text/prompt.

The LLM turns the finished script into packaging that maximizes click-through while
staying honest to the content. Falls back to a plain template built from the script
when no LLM key is present, so the pipeline still produces valid metadata offline.
"""
from __future__ import annotations

from ..core.log import get_logger
from ..llm import client as llm
from ..plan.schemas import METADATA_SCHEMA

log = get_logger(__name__)

_SYSTEM = (
    "You are a YouTube growth specialist. You write titles that earn the click without "
    "lying (curiosity gap, stakes, specificity), descriptions that front-load the hook "
    "and include a few relevant hashtags, and tight tag lists. Thumbnail text is 3-5 "
    "punchy words. Keep everything brand-safe and copyright-safe."
)


def _prompt(selection: dict, script: dict) -> str:
    narration = " ".join(s.get("narration", "") for s in script.get("scenes", []))
    return f"""Package this finished video for YouTube.

NICHE: {selection['niche']}
FORMAT: {selection['format']}  (a {'Short' if selection['format'] == 'short' else 'long-form video'})
WORKING TITLE: {script.get('title_working', selection['topic'])}
HOOK: {script.get('hook', '')}
FULL NARRATION: {narration[:1500]}

Return JSON only:
- title: <=100 chars, scroll-stopping, no clickbait lies.
- description: 2-4 sentences, hook first, end with 3-5 relevant #hashtags.
- tags: 8-15 lowercase search tags.
- thumbnail_text: 3-5 words, high-contrast punch.
- thumbnail_prompt: a vivid text-to-image prompt for the thumbnail background
  (cinematic, high-contrast, leaves room for the text; copyright-safe)."""


def _template(selection: dict, script: dict) -> dict:
    topic = script.get("title_working", selection["topic"])
    return {
        "title": topic[:100],
        "description": (f"{script.get('hook', topic)}\n\n"
                        f"#shorts #{selection['niche'].replace('-', '')} #facts"),
        "tags": list(dict.fromkeys(
            [selection["niche"], "facts", "shorts", "didyouknow"]
            + [w.lower() for w in topic.split() if len(w) > 3][:8]
        )),
        "thumbnail_text": " ".join(topic.split()[:4]).upper(),
        "thumbnail_prompt": f"{topic}, {selection.get('style', 'cinematic')}, "
                            "dramatic high-contrast lighting, bold composition",
    }


def _sanitize(md: dict, selection: dict, script: dict) -> dict:
    tmpl = _template(selection, script)
    for key in ("title", "description", "thumbnail_text", "thumbnail_prompt"):
        if not md.get(key):
            md[key] = tmpl[key]
    md["title"] = str(md["title"])[:100]
    tags = md.get("tags")
    if not isinstance(tags, list) or not tags:
        md["tags"] = tmpl["tags"]
    else:
        md["tags"] = [str(t)[:40] for t in tags][:15]
    return md


def generate(selection: dict, script: dict) -> dict:
    if llm.available():
        try:
            md = llm.complete_json(_prompt(selection, script),
                                   schema=METADATA_SCHEMA, system=_SYSTEM)
            md = _sanitize(md, selection, script)
            log.info("[metadata] LLM title: %s", md["title"])
            return md
        except Exception as exc:  # noqa: BLE001
            log.warning("[metadata] LLM failed (%s) -> template", exc)
    md = _template(selection, script)
    log.info("[metadata] template title: %s", md["title"])
    return md
