"""Text-to-speech voice ladder + per-scene prosody.

Ladder (expressive first, reliable last), each tried in the configured order and
skipped when unavailable:
    Chatterbox (HF Space, emotive)  -> Kokoro (HF Space, natural, light)
      -> Gemini TTS (cloud free tier, natural + style-promptable) -> edge-tts (always works)

edge-tts is the reliable workhorse and the only engine that returns word-level
WordBoundary timings for free; when an expressive engine is used instead, captions
fall back to Groq Whisper forced-alignment (see subtitles.py) or an even split.

Prosody: the narrator's delivery is shaped per scene by the niche playbook's voice
config PLUS the scene's beat role — the hook and the payoff are delivered more
deliberately (punchy), the middle stays brisk — which measurably helps retention.

Public API:
    synth(text, out_path, voice_cfg=None) -> {"audio", "duration", "words", "engine"}
    synth_scenes(scenes, out_dir, voice_cfg=None) -> per-scene results (global-timed words)
"""
from __future__ import annotations

import asyncio
import base64
import json
import re
import shutil
import subprocess
import wave
from pathlib import Path

from ..core.config import env, load_config
from ..core.fallback import Provider, try_providers
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()

GEMINI_TTS_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _ffprobe_duration(path: Path) -> float:
    try:
        out = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "json", str(path)],
            capture_output=True, text=True, check=True,
        )
        return float(json.loads(out.stdout)["format"]["duration"])
    except Exception:  # noqa: BLE001
        return 0.0


# --------------------------------------------------------------------------- #
# Audio mastering (loudness normalization) — optional, guarded
# --------------------------------------------------------------------------- #
_FFMPEG = shutil.which("ffmpeg") or shutil.which("ffmpeg.exe")


def master_file(path: Path) -> None:
    """Loudness-normalize a narration file in place (EBU R128 via ffmpeg loudnorm).

    Keeps scene levels consistent across engines/scenes. loudnorm preserves
    duration, so timings are unaffected. If ffmpeg is unavailable or the pass fails,
    the original file is left untouched.
    """
    if not _cfg.get("providers.tts.loudnorm", True) or not _FFMPEG:
        return
    path = Path(path)
    tmp = path.with_name(path.stem + "_norm" + path.suffix)
    target = _cfg.get("providers.tts.loudnorm_i", -16)
    try:
        subprocess.run(
            [_FFMPEG, "-y", "-i", str(path),
             "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11",
             "-ar", "44100", str(tmp)],
            capture_output=True, check=True,
        )
        if tmp.exists() and tmp.stat().st_size > 512:
            tmp.replace(path)
    except Exception as exc:  # noqa: BLE001
        log.debug("[tts] loudnorm skipped for %s: %s", path.name, exc)
        try:
            tmp.unlink(missing_ok=True)
        except Exception:  # noqa: BLE001
            pass


# --------------------------------------------------------------------------- #
# Prosody helpers
# --------------------------------------------------------------------------- #
def _shift_percent(pct: str, delta: int) -> str:
    """Shift an edge-tts rate/pitch percent string, e.g. ('+6%', -6) -> '+0%'."""
    try:
        base = int(re.sub(r"[^0-9+-]", "", pct or "+0%") or 0)
    except ValueError:
        base = 0
    val = base + delta
    return f"{'+' if val >= 0 else ''}{val}%"


def scene_role(index: int, n: int) -> str:
    """Map a scene position to a delivery role."""
    if index == 0:
        return "hook"
    if index >= n - 1:
        return "payoff"
    return "body"


_ROLE_STYLE = {
    "hook": "Deliver this opening line with intrigue and suspense, hooking the listener",
    "body": "Deliver this clearly and briskly, keeping momentum",
    "payoff": "Deliver this closing line with emphasis, weight and a sense of finality",
}


def prosody_for(voice_cfg: dict | None, index: int, n: int) -> dict:
    """Return a per-scene voice_cfg: base playbook voice + a beat-role adjustment.

    Hook/payoff are slowed slightly (more deliberate = punchier); the body keeps the
    niche's base pace. A natural-language `style` hint is attached for engines that
    accept one (Gemini TTS)."""
    vc = dict(voice_cfg or {})
    role = scene_role(index, n)
    rate_delta = {"hook": -6, "body": 0, "payoff": -6}[role]
    vc["edge_rate"] = _shift_percent(vc.get("edge_rate")
                                     or _cfg.get("providers.tts.edge_rate", "+0%"), rate_delta)
    base_style = vc.get("style", "")
    vc["style_hint"] = f"{_ROLE_STYLE[role]}. Tone: {base_style}." if base_style else _ROLE_STYLE[role]
    vc["_role"] = role
    return vc


# --------------------------------------------------------------------------- #
# edge-tts (reliable; native word timings)
# --------------------------------------------------------------------------- #
async def _edge_async(text: str, out_path: Path, voice_cfg: dict | None = None) -> list[dict]:
    import edge_tts
    vc = voice_cfg or {}
    voice = vc.get("edge_voice") or _cfg.get("providers.tts.edge_voice", "en-US-AriaNeural")
    rate = vc.get("edge_rate") or _cfg.get("providers.tts.edge_rate", "+0%")
    pitch = vc.get("edge_pitch") or _cfg.get("providers.tts.edge_pitch", "+0Hz")
    comm = edge_tts.Communicate(text, voice=voice, rate=rate, pitch=pitch,
                                boundary="WordBoundary")
    words: list[dict] = []
    with open(out_path, "wb") as fh:
        async for chunk in comm.stream():
            if chunk["type"] == "audio":
                fh.write(chunk["data"])
            elif chunk["type"] == "WordBoundary":
                start = chunk["offset"] / 1e7          # 100ns -> seconds
                dur = chunk["duration"] / 1e7
                words.append({"word": chunk["text"], "start": round(start, 3),
                              "end": round(start + dur, 3)})
    return words


def _edge(text: str, out_path: Path, voice_cfg: dict | None = None) -> dict:
    words = asyncio.run(_edge_async(text, out_path, voice_cfg))
    dur = _ffprobe_duration(out_path) or (words[-1]["end"] if words else 0.0)
    return {"audio": out_path, "duration": dur, "words": words, "engine": "edge"}


# --------------------------------------------------------------------------- #
# Gemini TTS (cloud, free tier; natural + style-promptable)
# --------------------------------------------------------------------------- #
def _pcm_to_wav(pcm: bytes, out_path: Path, rate: int = 24000, channels: int = 1,
                sampwidth: int = 2) -> None:
    with wave.open(str(out_path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(sampwidth)
        wf.setframerate(rate)
        wf.writeframes(pcm)


def _parse_pcm_rate(mime: str, default: int = 24000) -> int:
    m = re.search(r"rate=(\d+)", mime or "")
    return int(m.group(1)) if m else default


def _gemini_tts(text: str, out_path: Path, voice_cfg: dict | None = None) -> dict:
    from ..core import http
    key = env("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    model = _cfg.get("providers.tts.gemini_model", "gemini-2.5-flash-preview-tts")
    voice_name = _cfg.get("providers.tts.gemini_voice", "Kore")
    vc = voice_cfg or {}
    style = vc.get("style_hint") or vc.get("style") or ""
    prompt = f"{style}\n\n{text}" if style else text
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {
            "responseModalities": ["AUDIO"],
            "speechConfig": {"voiceConfig": {"prebuiltVoiceConfig": {"voiceName": voice_name}}},
        },
    }
    data = http.post_json(
        GEMINI_TTS_URL.format(model=model), params={"key": key}, json=body,
        cache=False, headers={"Content-Type": "application/json"},
    )
    try:
        part = data["candidates"][0]["content"]["parts"][0]["inlineData"]
        pcm = base64.b64decode(part["data"])
        rate = _parse_pcm_rate(part.get("mimeType", ""))
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Gemini TTS unexpected response: {json.dumps(data)[:200]}") from exc
    wav_path = out_path.with_suffix(".wav")
    _pcm_to_wav(pcm, wav_path, rate=rate)
    dur = _ffprobe_duration(wav_path) or (len(pcm) / (rate * 2))
    return {"audio": wav_path, "duration": dur, "words": [], "engine": "gemini_tts"}


# --------------------------------------------------------------------------- #
# HF-Space engines (optional, expressive) — Chatterbox & Kokoro via gradio_client
# --------------------------------------------------------------------------- #
def _hf_space_tts(text: str, out_path: Path, space: str, api_name: str, engine: str) -> dict:
    from gradio_client import Client
    client = Client(space)
    result = client.predict(text, api_name=api_name)
    src = Path(result if isinstance(result, str) else result[0])
    dest = out_path.with_suffix(src.suffix or ".wav")
    dest.write_bytes(src.read_bytes())
    dur = _ffprobe_duration(dest)
    return {"audio": dest, "duration": dur, "words": [], "engine": engine}


def _chatterbox(text: str, out_path: Path, voice_cfg: dict | None = None) -> dict:
    space = _cfg.get("providers.tts.chatterbox_space", "")
    if not space:
        raise RuntimeError("no chatterbox_space configured")
    api = _cfg.get("providers.tts.chatterbox_api", "/generate")
    return _hf_space_tts(text, out_path, space, api, "chatterbox")


def _kokoro(text: str, out_path: Path, voice_cfg: dict | None = None) -> dict:
    space = _cfg.get("providers.tts.kokoro_space", "")
    if not space:
        raise RuntimeError("no kokoro_space configured")
    api = _cfg.get("providers.tts.kokoro_api", "/generate")
    return _hf_space_tts(text, out_path, space, api, "kokoro")


# --------------------------------------------------------------------------- #
# Provider assembly + public API
# --------------------------------------------------------------------------- #
def _providers(text: str, out_path: Path, voice_cfg: dict | None = None):
    order = _cfg.get("providers.tts.order", ["chatterbox", "kokoro", "gemini_tts", "edge"])
    impls = {
        "chatterbox": Provider("chatterbox", lambda: _chatterbox(text, out_path, voice_cfg),
                               available=bool(_cfg.get("providers.tts.chatterbox_space"))),
        "kokoro": Provider("kokoro", lambda: _kokoro(text, out_path, voice_cfg),
                           available=bool(_cfg.get("providers.tts.kokoro_space"))),
        "gemini_tts": Provider("gemini_tts", lambda: _gemini_tts(text, out_path, voice_cfg),
                               available=bool(env("GEMINI_API_KEY"))
                               and bool(_cfg.get("providers.tts.use_gemini", True))),
        "edge": Provider("edge", lambda: _edge(text, out_path, voice_cfg), available=True),
    }
    return [impls[n] for n in order if n in impls]


def synth(text: str, out_path: Path, voice_cfg: dict | None = None) -> dict:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    return try_providers("tts", _providers(text, out_path, voice_cfg))


def synth_scenes(scenes: list[dict], out_dir: Path,
                 voice_cfg: dict | None = None) -> list[dict]:
    """Synthesize each scene; return per-scene audio + duration + global-timed words.

    `voice_cfg` (from the resolved niche playbook) sets the narrator; per scene we
    additionally apply a beat-role prosody adjustment (hook/payoff punchier).
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if voice_cfg:
        log.info("[tts] narrator voice=%s base_rate=%s (%s)",
                 voice_cfg.get("edge_voice"), voice_cfg.get("edge_rate"),
                 voice_cfg.get("style", ""))
    results: list[dict] = []
    cursor = 0.0
    n = len(scenes)
    for i, scene in enumerate(scenes):
        text = scene.get("narration", "").strip() or "..."
        vc = prosody_for(voice_cfg, i, n)
        res = synth(text, out_dir / f"scene_{i:02d}.mp3", vc)
        master_file(Path(res["audio"]))
        res["duration"] = _ffprobe_duration(Path(res["audio"])) or res["duration"]
        gwords = [{"word": w["word"], "start": round(w["start"] + cursor, 3),
                   "end": round(w["end"] + cursor, 3)} for w in res["words"]]
        results.append({
            "index": i,
            "audio": str(res["audio"]),
            "duration": res["duration"],
            "start": round(cursor, 3),
            "words": gwords,
            "engine": res["engine"],
            "role": vc.get("_role"),
        })
        cursor += res["duration"]
    engines = sorted({r["engine"] for r in results})
    log.info("[tts] synthesized %d scenes, total %.1fs (engines: %s)",
             len(results), cursor, ", ".join(engines))
    return results
