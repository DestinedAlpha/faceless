"""Provider smoke test: hit every adapter once and print pass/fail.

Run:  python scripts/smoke_test.py

Proves each free provider is *actually* reachable before wiring a full run.
Nothing here is required to pass — the pipeline degrades gracefully — but a green
row means that layer is live with the keys currently in `.env`. Providers with no
key are reported as SKIP (not a failure).

Exit code is 0 as long as every *core* layer that can run keyless works
(LLM-optional, images via Pollinations, TTS via edge-tts). Missing optional keys
never fail the run.
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

# Make `faceless` importable when run as `python scripts/smoke_test.py`.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faceless.core.config import env, load_config  # noqa: E402
from faceless.core.log import get_logger, setup_logging  # noqa: E402

setup_logging("INFO")
log = get_logger("smoke")
_cfg = load_config()

PASS, FAIL, SKIP = "PASS", "FAIL", "SKIP"
_results: list[tuple[str, str, str]] = []


def _record(layer: str, status: str, detail: str = "") -> None:
    _results.append((layer, status, detail))
    icon = {"PASS": "[green]PASS[/]", "FAIL": "[red]FAIL[/]", "SKIP": "[yellow]SKIP[/]"}[status]
    log.info("%-14s %s  %s", layer, icon, detail)


def _time(fn):
    t0 = time.time()
    out = fn()
    return out, time.time() - t0


# --------------------------------------------------------------------------- #
# Individual checks
# --------------------------------------------------------------------------- #
def check_llm() -> None:
    from faceless.llm import client as llm
    if not llm.available():
        _record("llm", SKIP, "no GEMINI_API_KEY / GROQ_API_KEY")
        return
    try:
        txt, dt = _time(lambda: llm.complete(
            "Reply with exactly the word: pong.", system="You are terse."))
        ok = "pong" in txt.lower()
        _record("llm", PASS if ok else FAIL, f"{txt.strip()[:40]!r} in {dt:.1f}s")
    except Exception as exc:  # noqa: BLE001
        _record("llm", FAIL, str(exc)[:120])


def check_youtube() -> None:
    from faceless.trends import youtube
    if not youtube.available():
        _record("youtube", SKIP, "no YOUTUBE_API_KEY")
        return
    try:
        items, dt = _time(youtube.fetch)
        _record("youtube", PASS if items else FAIL,
                f"{len(items)} videos in {dt:.1f}s")
    except Exception as exc:  # noqa: BLE001
        _record("youtube", FAIL, str(exc)[:120])


def check_reddit() -> None:
    from faceless.trends import reddit
    if not reddit.available():
        _record("reddit", SKIP, "no REDDIT_CLIENT_ID / SECRET")
        return
    try:
        items, dt = _time(reddit.fetch)
        _record("reddit", PASS if items else FAIL,
                f"{len(items)} posts in {dt:.1f}s")
    except Exception as exc:  # noqa: BLE001
        _record("reddit", FAIL, str(exc)[:120])


def check_images(tmp: Path) -> None:
    from faceless.assets import images
    try:
        out = tmp / "smoke_image.jpg"
        _, dt = _time(lambda: images.generate(
            "a single red apple on a white table, studio light", out, 512, 512, seed=1))
        size = out.stat().st_size if out.exists() else 0
        _record("images", PASS if size > 1024 else FAIL,
                f"{size//1024} KB in {dt:.1f}s (Pollinations)")
    except Exception as exc:  # noqa: BLE001
        _record("images", FAIL, str(exc)[:120])


def check_tts(tmp: Path) -> None:
    from faceless.assets import tts
    try:
        out = tmp / "smoke_tts.mp3"
        res, dt = _time(lambda: tts.synth("This is a free text to speech test.", out))
        words = len(res.get("words", []))
        ok = out.exists() and out.stat().st_size > 1024
        _record("tts", PASS if ok else FAIL,
                f"{res.get('engine')} {res.get('duration',0):.1f}s, "
                f"{words} word-timings in {dt:.1f}s")
    except Exception as exc:  # noqa: BLE001
        _record("tts", FAIL, str(exc)[:120])


def check_stock(tmp: Path) -> None:
    from faceless.assets import stock
    if not stock.available():
        _record("stock", SKIP, "no PEXELS_API_KEY / PIXABAY_API_KEY")
        return
    try:
        out = tmp / "smoke_broll.mp4"
        res, dt = _time(lambda: stock.fetch_broll("ocean waves", out, portrait=True))
        ok = bool(res) and out.exists() and out.stat().st_size > 1024
        _record("stock", PASS if ok else FAIL,
                (f"{out.stat().st_size//1024} KB in {dt:.1f}s" if ok
                 else "no clip returned"))
    except Exception as exc:  # noqa: BLE001
        _record("stock", FAIL, str(exc)[:120])


def check_node() -> None:
    import shutil
    node = shutil.which("node") or (shutil.which("node.exe"))
    npx = shutil.which("npx") or shutil.which("npx.cmd")
    remotion_installed = (_cfg.root / "remotion" / "node_modules" / "remotion").exists()
    if not node:
        _record("node", FAIL, "node not found on PATH (needed to render)")
        return
    detail = f"node={node}"
    if not npx:
        detail += "  (npx missing!)"
    detail += "  remotion deps: " + ("installed" if remotion_installed
                                      else "not yet (auto on first render)")
    _record("node", PASS if npx else FAIL, detail)


# --------------------------------------------------------------------------- #
def check_learn() -> None:
    """Phase 6 learn loop: store readable + report which ingest path is live."""
    try:
        from faceless.learn import store
        from faceless.learn import youtube_analytics as yt
        rows = store.read_rows()
        auto = "OAuth pull" if yt.available() else "manual inbox only"
        _record("learn", PASS, f"{len(rows)} perf row(s); {auto}")
    except Exception as exc:  # noqa: BLE001
        _record("learn", FAIL, str(exc)[:120])


# --------------------------------------------------------------------------- #
def main() -> int:
    tmp = _cfg.cache_dir / "smoke"
    tmp.mkdir(parents=True, exist_ok=True)

    log.info("[bold]Faceless provider smoke test[/]  (keys read from .env)")
    check_node()
    check_llm()
    check_youtube()
    check_reddit()
    check_images(tmp)
    check_tts(tmp)
    check_stock(tmp)
    check_learn()

    fails = [r for r in _results if r[1] == FAIL]
    passes = [r for r in _results if r[1] == PASS]
    skips = [r for r in _results if r[1] == SKIP]
    log.info("")
    log.info("[bold]Summary[/]: %d pass, %d fail, %d skip",
             len(passes), len(fails), len(skips))

    # Only *core keyless* layers failing should fail the smoke test.
    core = {"images", "tts", "node"}
    core_fail = [r for r in fails if r[0] in core]
    if core_fail:
        log.error("core layers failing: %s", ", ".join(r[0] for r in core_fail))
        return 1
    if fails:
        log.warning("optional layers failing (run still works): %s",
                    ", ".join(r[0] for r in fails))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
