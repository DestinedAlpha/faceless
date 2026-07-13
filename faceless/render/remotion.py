"""Remotion bridge: stage assets, write video_spec.json, invoke `remotion render`.

The composition resolves every asset via staticFile("render/<basename>"), so this
bridge copies the run's real files (per-scene images/clips, per-scene narration
audio, optional music) into remotion/public/render/ under their basenames — exactly
the names spec.build_spec emitted. The spec itself is passed to Remotion as
inputProps (--props), which its calculateMetadata reads for size/fps/duration.

npm install is run once on demand if node_modules is missing.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from ..core.config import load_config
from ..core.log import get_logger
from ..core.util import write_json

log = get_logger(__name__)
_cfg = load_config()

COMPOSITION_ID = "Faceless"


def _remotion_dir() -> Path:
    return _cfg.root / "remotion"


def _is_windows() -> bool:
    return os.name == "nt"


def _resolve_exe(name: str) -> str:
    """Find a runnable path for a Node CLI (npm/npx).

    On Windows these are `.cmd` shims. We resolve the full path via shutil.which
    so we can invoke them WITHOUT shell=True — that keeps every list argument
    intact even when paths contain spaces (e.g. "yt thing"), which is exactly the
    case that previously made Remotion write to the wrong location.
    """
    found = shutil.which(name)
    if found:
        return found
    if _is_windows():
        found = shutil.which(f"{name}.cmd") or shutil.which(f"{name}.exe")
        if found:
            return found
        return f"{name}.cmd"  # last resort; CreateProcess resolves via PATHEXT
    return name


def _run(cmd: list[str], cwd: Path) -> None:
    """Run a subprocess with shell=False so args (incl. spaced paths) pass verbatim."""
    exe = _resolve_exe(cmd[0])
    full = [exe, *cmd[1:]]
    log.debug("[remotion] exec: %s (cwd=%s)", full, cwd)
    subprocess.run(full, cwd=str(cwd), check=True)


def _ensure_deps(remotion_dir: Path) -> None:
    if (remotion_dir / "node_modules" / "remotion").exists():
        return
    log.info("[remotion] node_modules missing -> running `npm install` (one-time)")
    _run(["npm", "install"], cwd=remotion_dir)


def _stage_assets(assets: list[Path], render_dir: Path) -> None:
    """Copy every source asset into public/render/ under its basename."""
    render_dir.mkdir(parents=True, exist_ok=True)
    # Clean stale files from a previous run so nothing leaks across renders.
    for old in render_dir.iterdir():
        if old.is_file():
            old.unlink()
    for src in assets:
        if src is None:
            continue
        src = Path(src)
        if not src.exists():
            log.warning("[remotion] asset missing, skipping: %s", src)
            continue
        shutil.copy2(src, render_dir / src.name)


def render(*, spec: dict, assets: list[Path], out_path: Path) -> Path:
    """Render the video. `assets` = every file the spec references by basename
    (scene images/clips, scene audio, music). Returns the final mp4 path."""
    remotion_dir = _remotion_dir()
    if not remotion_dir.exists():
        raise FileNotFoundError(f"remotion project not found at {remotion_dir}")

    _ensure_deps(remotion_dir)

    render_dir = remotion_dir / "public" / "render"
    _stage_assets([Path(a) for a in assets if a], render_dir)

    # Spec doubles as inputProps; also drop a copy alongside the staged assets.
    spec_path = render_dir / "video_spec.json"
    write_json(spec_path, spec)

    # Absolute: remotion runs with cwd=remotion_dir, so a relative output path
    # would otherwise be written under remotion/ instead of where the caller meant.
    out_path = Path(out_path).resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    concurrency = int(_cfg.get("render.remotion_concurrency", 2))
    crf = int(_cfg.get("render.remotion_crf", 18))

    def _cmd(conc: int) -> list[str]:
        return [
            "npx", "remotion", "render",
            "src/index.ts", COMPOSITION_ID, str(out_path),
            f"--props={spec_path}",
            f"--concurrency={conc}",
            f"--crf={crf}",
            "--log=info",
        ]

    # Chromium render tabs can OOM-crash ("Page crashed!", non-zero exit) on long
    # heavy compositions (parallax layers + grade + captions) when several tabs run
    # in parallel. If a multi-tab render fails, fall back to a single tab — slower
    # but much lower peak memory — so a crash degrades to a slow success, not a fail.
    log.info("[remotion] rendering -> %s (concurrency=%d, crf=%d)",
             out_path, concurrency, crf)
    try:
        _run(_cmd(concurrency), cwd=remotion_dir)
    except subprocess.CalledProcessError as exc:
        if concurrency <= 1:
            raise
        log.warning("[remotion] render failed at concurrency=%d (%s) -> retry at 1",
                    concurrency, exc)
        _run(_cmd(1), cwd=remotion_dir)

    if not out_path.exists():
        # Robustness: some Node/OS/path combinations resolve the output relative
        # to the Remotion cwd instead of the absolute path we asked for. If the
        # file isn't where we expect, find the freshly-rendered mp4 by name and
        # move it into place rather than failing a completed render.
        relocated = _relocate_output(out_path, remotion_dir)
        if relocated is None:
            raise RuntimeError(
                f"remotion finished but output file is missing at {out_path}")
        out_path = relocated

    log.info("[remotion] done: %s (%.1f MB)", out_path,
             out_path.stat().st_size / 1e6)
    return out_path


def _relocate_output(expected: Path, remotion_dir: Path) -> Path | None:
    """Find a produced mp4 that landed somewhere other than `expected`.

    Remotion, when it resolves a relative-ish output, writes under its own cwd
    (e.g. remotion/output/<run>/<name>.mp4). Search the likely spots for a file
    with the expected basename and move it to `expected`. Returns the final path
    or None if nothing matching was found.
    """
    name = expected.name
    candidates = [
        remotion_dir / expected.parent.name / name,          # remotion/<run>/<name>
        remotion_dir / "output" / expected.parent.name / name,  # remotion/output/<run>/<name>
        remotion_dir / name,                                 # remotion/<name>
    ]
    # Fall back to a recursive scan under remotion_dir (excluding node_modules).
    for hit in candidates:
        if hit.exists():
            found = hit
            break
    else:
        found = None
        for p in remotion_dir.rglob(name):
            if "node_modules" in p.parts:
                continue
            found = p
            break

    if found is None:
        return None

    expected.parent.mkdir(parents=True, exist_ok=True)
    try:
        if found.resolve() == expected.resolve():
            return expected
        shutil.move(str(found), str(expected))
        log.warning("[remotion] output landed at %s -> moved to %s", found, expected)
        return expected
    except Exception as exc:  # noqa: BLE001
        log.warning("[remotion] could not relocate %s -> %s (%s); using original",
                    found, expected, exc)
        return found
