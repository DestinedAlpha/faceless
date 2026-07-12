"""Procedural sound-effects library — free, offline, deterministic.

Rather than depend on downloading copyrighted/rate-limited SFX packs, we SYNTHESIZE
a small library of clean, royalty-free cues with numpy (whoosh, riser, impact, pop,
click, ding, low-drone, shimmer, sweep) and cache them as 44.1kHz mono WAVs under
`assets_lib/sfx/`. This is 100% free, needs no network, and always works.

The script's per-scene `sfx` cue (e.g. "whoosh", "boom", "riser") is mapped to the
nearest synthesized asset; the renderer plays it at the start of that scene so cuts
and reveals land with a hit — a big, cheap perceived-quality lever.

Public API:
    ensure_library() -> dict[name, Path]     # synthesize any missing cues
    resolve(cue) -> Path | None              # map a script cue to an asset path
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

from ..core.config import load_config
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()

SFX_DIR = _cfg.root / "assets_lib" / "sfx"
SR = 44100

# Cue aliases -> canonical asset name.
_ALIASES = {
    "boom": "impact", "hit": "impact", "bang": "impact", "thud": "impact",
    "rise": "riser", "riser": "riser", "buildup": "riser", "build": "riser",
    "swoosh": "whoosh", "whoosh": "whoosh", "swipe": "whoosh", "transition": "whoosh",
    "woosh": "whoosh", "air": "whoosh",
    "pop": "pop", "bubble": "pop",
    "click": "click", "tick": "click", "tap": "click",
    "ding": "ding", "bell": "ding", "chime": "ding", "ping": "ding",
    "drone": "low-drone", "low-drone": "low-drone", "rumble": "low-drone", "sub": "low-drone",
    "shimmer": "shimmer", "sparkle": "shimmer", "twinkle": "shimmer", "magic": "shimmer",
    "sweep": "sweep", "crowd-roar": "riser", "crowd": "riser",
}

CANONICAL = ["whoosh", "riser", "impact", "pop", "click", "ding",
             "low-drone", "shimmer", "sweep"]


# --------------------------------------------------------------------------- #
# Low-level helpers
# --------------------------------------------------------------------------- #
def _t(seconds: float) -> np.ndarray:
    return np.linspace(0, seconds, int(SR * seconds), endpoint=False)


def _fade(sig: np.ndarray, fin: float = 0.005, fout: float = 0.02) -> np.ndarray:
    n = len(sig)
    ni, no = max(1, int(SR * fin)), max(1, int(SR * fout))
    env = np.ones(n)
    env[:ni] = np.linspace(0, 1, ni)
    env[-no:] = np.linspace(1, 0, no)
    return sig * env


def _norm(sig: np.ndarray, peak: float = 0.7) -> np.ndarray:
    m = np.max(np.abs(sig)) or 1.0
    return sig / m * peak


def _write(name: str, sig: np.ndarray) -> Path:
    SFX_DIR.mkdir(parents=True, exist_ok=True)
    sig = _norm(_fade(sig))
    pcm = (np.clip(sig, -1, 1) * 32767).astype("<i2").tobytes()
    path = SFX_DIR / f"{name}.wav"
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(SR)
        wf.writeframes(pcm)
    return path


def _pink(n: int) -> np.ndarray:
    """Approximate pink noise via cumulative-sum-filtered white noise."""
    rng = np.random.default_rng(1234)
    white = rng.standard_normal(n)
    # simple 1/f-ish smoothing
    b = np.cumsum(white)
    b = b - np.convolve(b, np.ones(64) / 64, mode="same")
    return b / (np.max(np.abs(b)) or 1.0)


# --------------------------------------------------------------------------- #
# Synths (each returns a mono float array in [-1,1])
# --------------------------------------------------------------------------- #
def _syn_whoosh() -> np.ndarray:
    t = _t(0.55)
    rng = np.random.default_rng(7)
    noise = rng.standard_normal(len(t))
    # moving band emphasis via time-varying gain + a swell envelope
    env = np.sin(np.pi * t / t[-1]) ** 2
    sweep = np.interp(t, [0, t[-1]], [0.2, 1.0])
    return noise * env * sweep


def _syn_riser() -> np.ndarray:
    t = _t(1.1)
    f = np.interp(t, [0, t[-1]], [180, 900])
    phase = 2 * np.pi * np.cumsum(f) / SR
    tone = np.sin(phase)
    rng = np.random.default_rng(3)
    noise = rng.standard_normal(len(t)) * 0.4
    env = (t / t[-1]) ** 2
    return (tone + noise) * env


def _syn_impact() -> np.ndarray:
    t = _t(0.6)
    f = np.interp(t, [0, t[-1]], [140, 45])
    body = np.sin(2 * np.pi * np.cumsum(f) / SR)
    click = np.zeros(len(t))
    click[: int(SR * 0.01)] = np.random.default_rng(9).standard_normal(int(SR * 0.01))
    env = np.exp(-t * 7)
    return body * env + click * 0.5


def _syn_pop() -> np.ndarray:
    t = _t(0.12)
    f = np.interp(t, [0, t[-1]], [700, 300])
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
    return tone * np.exp(-t * 30)


def _syn_click() -> np.ndarray:
    t = _t(0.05)
    n = np.random.default_rng(5).standard_normal(len(t))
    return n * np.exp(-t * 120)


def _syn_ding() -> np.ndarray:
    t = _t(0.9)
    partials = [(1.0, 1.0), (2.76, 0.5), (5.4, 0.25)]
    f0 = 880.0
    sig = sum(a * np.sin(2 * np.pi * f0 * r * t) for r, a in partials)
    return sig * np.exp(-t * 4.5)


def _syn_low_drone() -> np.ndarray:
    t = _t(1.6)
    sig = (np.sin(2 * np.pi * 55 * t) + np.sin(2 * np.pi * 55.4 * t)
           + 0.5 * np.sin(2 * np.pi * 110 * t))
    env = np.sin(np.pi * t / t[-1]) ** 0.5
    return sig * env


def _syn_shimmer() -> np.ndarray:
    t = _t(1.0)
    rng = np.random.default_rng(11)
    sig = np.zeros(len(t))
    for _ in range(12):
        f = rng.uniform(2000, 6000)
        start = rng.uniform(0, 0.6)
        env = np.clip(t - start, 0, None)
        env = env * np.exp(-(t - start) * 8) * (t > start)
        sig += np.sin(2 * np.pi * f * t) * env
    return sig


def _syn_sweep() -> np.ndarray:
    t = _t(0.7)
    f = np.interp(t, [0, t[-1]], [1200, 200])
    tone = np.sin(2 * np.pi * np.cumsum(f) / SR)
    env = np.sin(np.pi * t / t[-1]) ** 2
    return tone * env


_SYNTHS = {
    "whoosh": _syn_whoosh, "riser": _syn_riser, "impact": _syn_impact,
    "pop": _syn_pop, "click": _syn_click, "ding": _syn_ding,
    "low-drone": _syn_low_drone, "shimmer": _syn_shimmer, "sweep": _syn_sweep,
}


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def ensure_library() -> dict:
    """Synthesize any missing canonical SFX; return {name: Path}."""
    out: dict[str, Path] = {}
    made = 0
    for name in CANONICAL:
        path = SFX_DIR / f"{name}.wav"
        if not path.exists():
            try:
                _write(name, _SYNTHS[name]())
                made += 1
            except Exception as exc:  # noqa: BLE001
                log.warning("[sfx] failed to synth %s: %s", name, exc)
                continue
        out[name] = path
    if made:
        log.info("[sfx] synthesized %d cue(s) into %s", made, SFX_DIR)
    return out


def resolve(cue: str) -> Path | None:
    """Map a script sfx cue to a synthesized asset path (None if empty/unknown)."""
    if not cue:
        return None
    key = "".join(ch for ch in cue.strip().lower() if ch.isalnum() or ch in "- ")
    key = key.strip()
    # A canonical name (e.g. "impact") maps to itself; else consult the alias table.
    name = key if key in CANONICAL else _ALIASES.get(key)
    if not name:
        # try first token / substring match
        for alias, canon in _ALIASES.items():
            if alias in key:
                name = canon
                break
    if not name:
        return None
    lib = ensure_library()
    return lib.get(name)
