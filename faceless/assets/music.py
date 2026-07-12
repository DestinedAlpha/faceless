"""Background music: mood-matched local track -> procedural bed fallback.

Music is a real retention/perceived-quality lever, so instead of shipping silent
videos we ALWAYS provide a bed:

  1. If the user drops royalty-free tracks in `assets_lib/music/`, pick the one whose
     filename best matches the niche playbook's mood tags (else rotate).
  2. Otherwise SYNTHESIZE a subtle, mood-matched ambient/cinematic bed with numpy
     (chord pad + optional soft pulse), sized to the video length. 100% free, offline,
     copyright-safe, and it sits quietly under the narration (ducked at render time).

Public API:
    select(playbook, total_seconds, out_dir, seed=0) -> Path | None
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ..core.config import load_config
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()

MUSIC_DIR = _cfg.root / "assets_lib" / "music"
SR = 44100

# Mood -> musical character. (mode semitone set, tempo feel, pulse?)
_MINOR = [0, 3, 5, 7, 10]          # minor pentatonic (safe, always consonant)
_MAJOR = [0, 2, 4, 7, 9]           # major pentatonic
# Chord-root progressions (semitone offsets from the key root), looped.
_PROG_MINOR = [0, -4, 3, 5]        # i - VI - III(ish) - IV-ish movement
_PROG_MAJOR = [0, 5, 7, 5]         # I - IV - V - IV

_MOOD_MAP = {
    # energetic family
    "energetic": ("minor", 128, True), "hype": ("minor", 140, True),
    "trap": ("minor", 140, True), "upbeat": ("major", 120, True),
    "electronic": ("minor", 124, True), "light-electronic": ("major", 112, True),
    # epic / cinematic family
    "epic": ("minor", 90, False), "cinematic": ("minor", 84, False),
    "orchestral": ("minor", 80, False), "emotional": ("minor", 76, False),
    "cinematic-piano": ("minor", 78, False), "building": ("minor", 96, True),
    "triumphant": ("major", 100, True),
    # calm / awe family
    "ambient": ("minor", 70, False), "somber": ("minor", 66, False),
    "awe": ("minor", 68, False), "cosmic": ("minor", 64, False),
    "curious": ("major", 100, False), "uplifting": ("major", 104, False),
    "suspense": ("minor", 92, False),
}


def _mood_profile(playbook: dict | None) -> tuple[str, int, bool, str]:
    moods = ((playbook or {}).get("music", {}) or {}).get("mood", []) or ["cinematic"]
    for m in moods:
        key = str(m).strip().lower()
        if key in _MOOD_MAP:
            mode, bpm, pulse = _MOOD_MAP[key]
            return mode, bpm, pulse, key
    return "minor", 90, False, str(moods[0]).lower()


# --------------------------------------------------------------------------- #
# Local library
# --------------------------------------------------------------------------- #
def _pick_local(playbook: dict | None, seed: int) -> Path | None:
    if not MUSIC_DIR.exists():
        return None
    tracks = sorted(MUSIC_DIR.glob("*.mp3")) + sorted(MUSIC_DIR.glob("*.m4a")) \
        + sorted(MUSIC_DIR.glob("*.wav"))
    if not tracks:
        return None
    moods = ((playbook or {}).get("music", {}) or {}).get("mood", []) or []
    moods = [str(m).lower() for m in moods]
    # Prefer a track whose filename contains a mood tag.
    for mood in moods:
        for t in tracks:
            if mood in t.stem.lower():
                log.info("[music] local mood match '%s' -> %s", mood, t.name)
                return t
    chosen = tracks[seed % len(tracks)]
    log.info("[music] local track (rotating): %s", chosen.name)
    return chosen


# --------------------------------------------------------------------------- #
# Procedural bed
# --------------------------------------------------------------------------- #
def _midi(semitone: int, root_hz: float = 130.81) -> float:  # C3 root
    return root_hz * (2 ** (semitone / 12.0))


def _pad_note(freq: float, dur: float, attack: float = 0.4, release: float = 0.8) -> np.ndarray:
    t = np.linspace(0, dur, int(SR * dur), endpoint=False)
    # soft tone: fundamental + gentle octave + fifth, low harmonics only
    tone = (np.sin(2 * np.pi * freq * t)
            + 0.5 * np.sin(2 * np.pi * freq * 2 * t)
            + 0.3 * np.sin(2 * np.pi * freq * 1.5 * t))
    env = np.ones(len(t))
    na, nr = int(SR * attack), int(SR * release)
    if na:
        env[:na] = np.linspace(0, 1, na)
    if nr:
        env[-nr:] *= np.linspace(1, 0, nr)
    return tone * env


def _synthesize_bed(playbook: dict, total_seconds: float, out_dir: Path,
                    seed: int) -> Path | None:
    try:
        mode, bpm, pulse, mood = _mood_profile(playbook)
        scale = _MINOR if mode == "minor" else _MAJOR
        prog = _PROG_MINOR if mode == "minor" else _PROG_MAJOR
        rng = np.random.default_rng(seed + 42)

        beat = 60.0 / bpm
        bar = beat * 4
        total = max(total_seconds + 1.0, bar * 2)
        n_bars = int(np.ceil(total / bar))
        buf = np.zeros(int(SR * (n_bars * bar)) + SR)

        for b in range(n_bars):
            root = prog[b % len(prog)]
            start = int(b * bar * SR)
            # chord pad: root, third-ish, fifth from the scale
            for deg in (0, 2, 4):
                semi = root + scale[deg % len(scale)]
                note = _pad_note(_midi(semi), bar, attack=min(0.5, bar * 0.3),
                                 release=min(1.0, bar * 0.4)) * 0.28
                end = start + len(note)
                if end <= len(buf):
                    buf[start:end] += note
            # optional gentle melodic sparkle high above
            if not pulse and b % 2 == 0:
                semi = root + scale[rng.integers(0, len(scale))] + 12
                mel = _pad_note(_midi(semi) * 2, beat * 2, attack=0.05, release=0.6) * 0.06
                s2 = start + int(beat * SR)
                if s2 + len(mel) <= len(buf):
                    buf[s2:s2 + len(mel)] += mel

        if pulse:
            # soft sub pulse on each beat for energetic moods
            n_beats = int(n_bars * 4)
            for k in range(n_beats):
                s = int(k * beat * SR)
                td = np.linspace(0, 0.12, int(SR * 0.12), endpoint=False)
                f = np.interp(td, [0, td[-1]], [90, 50])
                kick = np.sin(2 * np.pi * np.cumsum(f) / SR) * np.exp(-td * 18) * 0.4
                if s + len(kick) <= len(buf):
                    buf[s:s + len(kick)] += kick

        # trim to exact length, gentle low-pass (moving average), fades, normalize
        buf = buf[: int(SR * total)]
        buf = np.convolve(buf, np.ones(8) / 8, mode="same")
        nf = int(SR * 1.0)
        if len(buf) > 2 * nf:
            buf[:nf] *= np.linspace(0, 1, nf)
            buf[-nf:] *= np.linspace(1, 0, nf)
        buf = buf / (np.max(np.abs(buf)) or 1.0) * 0.5

        out_dir.mkdir(parents=True, exist_ok=True)
        path = out_dir / "music_bed.wav"
        pcm = (np.clip(buf, -1, 1) * 32767).astype("<i2").tobytes()
        with wave.open(str(path), "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(SR)
            wf.writeframes(pcm)
        log.info("[music] synthesized %s bed (%s, %d bpm, %.0fs)", mood, mode, bpm, total)
        return path
    except Exception as exc:  # noqa: BLE001
        log.warning("[music] procedural bed failed: %s", exc)
        return None


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def select(playbook: dict | None, total_seconds: float, out_dir: Path,
           seed: int = 0) -> Path | None:
    if not _cfg.get("render.music.enabled", True):
        return None
    local = _pick_local(playbook, seed)
    if local:
        return local
    if _cfg.get("render.music.synthesize", True):
        return _synthesize_bed(playbook or {}, total_seconds, out_dir, seed)
    log.info("[music] no local track and synthesis disabled -> narration only")
    return None


# Backwards-compatible thin wrapper (older callers).
def pick_track(seed: int = 0) -> Path | None:
    return _pick_local(None, seed)
