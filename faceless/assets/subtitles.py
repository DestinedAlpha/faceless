"""Caption tokens for karaoke-style word highlight.

Given per-scene TTS results (each with global-timed words), build caption groups:
small runs of words (<= max_words_per_group) that appear together, each word
carrying its own start/end so Remotion can highlight the active word.

If a scene has no word timings (e.g. Chatterbox path), we fall back to Groq
Whisper for forced alignment when available, else evenly distribute words across
the scene duration.
"""
from __future__ import annotations

from ..core.config import env, load_config
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()


def _even_words(text: str, start: float, duration: float) -> list[dict]:
    toks = text.split()
    if not toks:
        return []
    per = duration / len(toks)
    return [{"word": t, "start": round(start + i * per, 3),
             "end": round(start + (i + 1) * per, 3)} for i, t in enumerate(toks)]


def _groq_whisper_words(audio_path: str, offset: float) -> list[dict] | None:
    """Word timestamps via Groq Whisper (2000 req/day free). None if unavailable."""
    if not env("GROQ_API_KEY"):
        return None
    try:
        from ..core import http
        model = _cfg.get("providers.subtitles.groq_whisper_model", "whisper-large-v3-turbo")
        with open(audio_path, "rb") as fh:
            files = {"file": (audio_path, fh, "audio/mpeg")}
            data = {"model": model, "response_format": "verbose_json",
                    "timestamp_granularities[]": "word"}
            resp = http.client().post(
                "https://api.groq.com/openai/v1/audio/transcriptions",
                headers={"Authorization": f"Bearer {env('GROQ_API_KEY')}"},
                files=files, data=data, timeout=120,
            )
        resp.raise_for_status()
        j = resp.json()
        words = j.get("words") or []
        return [{"word": w["word"], "start": round(w["start"] + offset, 3),
                 "end": round(w["end"] + offset, 3)} for w in words]
    except Exception as exc:  # noqa: BLE001
        log.warning("[subtitles] groq whisper failed: %s", exc)
        return None


_EMPH_STOP = set("""
a an the of to in on for and or but with your you my our it is are was were be as at by
this that these those from into over under about how why what when who which just like
""".split())


def _mark_emphasis(chunk: list[dict]) -> None:
    """Flag the most 'content-heavy' word in a caption group so the renderer can
    punch it. Heuristic: the longest non-stopword; ties -> the last one."""
    best_i, best_len = -1, 0
    for i, w in enumerate(chunk):
        token = "".join(ch for ch in w["word"].lower() if ch.isalnum())
        if not token or token in _EMPH_STOP:
            continue
        if len(token) >= best_len:
            best_i, best_len = i, len(token)
    for i, w in enumerate(chunk):
        w["emphasis"] = (i == best_i)


def build_captions(scene_audio: list[dict], scenes: list[dict],
                   playbook: dict | None = None) -> list[dict]:
    """Return caption groups: {start, end, words:[{word,start,end,emphasis}]}.

    Group size + whether to mark an emphasis word come from the niche playbook
    (falling back to config), so caption cadence matches the format.
    """
    caps = (playbook or {}).get("captions", {})
    max_words = int(caps.get("max_words_per_group")
                    or _cfg.get("render.captions.max_words_per_group", 4))
    do_emphasis = bool(caps.get("emphasis", _cfg.get("render.captions.emphasis", True)))
    groups: list[dict] = []

    for sa in scene_audio:
        words = sa.get("words") or []
        if not words:  # no boundaries (chatterbox) -> whisper, else even split
            words = _groq_whisper_words(sa["audio"], sa["start"])
        if not words:
            text = scenes[sa["index"]].get("narration", "")
            words = _even_words(text, sa["start"], sa["duration"])

        for i in range(0, len(words), max_words):
            chunk = words[i:i + max_words]
            if not chunk:
                continue
            if do_emphasis:
                _mark_emphasis(chunk)
            groups.append({
                "start": chunk[0]["start"],
                "end": chunk[-1]["end"],
                "words": chunk,
            })

    log.info("[subtitles] built %d caption groups (max_words=%d, emphasis=%s)",
             len(groups), max_words, do_emphasis)
    return groups
