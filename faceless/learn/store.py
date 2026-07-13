"""The learning store: the memory that makes the loop compound.

Two artifacts live under `memory/` (project root, next to `playbooks/`):
  - `performance.jsonl` — one row per uploaded video's analytics snapshot, each
    joined back to the run that produced it (niche, hook shape, pacing, the title/
    thumbnail variant chosen, plus the real metrics). This is the raw evidence.
  - `learnings.md` — the distilled, human-readable rules `reflect.py` maintains.

This module owns the on-disk format and the *feature extraction* that turns a
finished `output/<run_id>/` folder back into the structured params we want to
correlate against performance. Everything is dependency-free and offline: reading
your own run folders never needs a network or a key.

Public API:
    perf_path(), learnings_path()
    read_rows() -> list[dict]
    upsert_rows(rows) -> int            # dedup by (run_id, video_id), newest wins
    run_features(run_id | run_dir) -> dict | None
    classify_hook(hook_text) -> str
    metric_defaults() -> dict
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable

from ..core.config import load_config
from ..core.log import get_logger
from ..core.util import read_json

log = get_logger(__name__)
_cfg = load_config()

MEMORY_DIR = _cfg.root / "memory"

# The metric fields the checklist asks you to report back (and the OAuth pull
# fills automatically). Kept in one place so ingest/reflect/backfill agree.
METRIC_FIELDS = (
    "views", "impressions", "ctr", "average_view_duration",
    "average_view_percentage", "retention_3s", "likes", "comments", "subs_gained",
)


def perf_path() -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR / "performance.jsonl"


def learnings_path() -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR / "learnings.md"


def metric_defaults() -> dict:
    return {k: None for k in METRIC_FIELDS}


# --------------------------------------------------------------------------- #
# performance.jsonl I/O
# --------------------------------------------------------------------------- #
def read_rows() -> list[dict]:
    p = perf_path()
    if not p.exists():
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            log.warning("[store] skipping malformed performance row")
    return rows


def _row_key(row: dict) -> str:
    """Identity for dedup: prefer run_id, else video_id, else the whole title."""
    return (row.get("run_id") or row.get("video_id")
            or row.get("title_used") or json.dumps(row, sort_keys=True))


def upsert_rows(rows: Iterable[dict]) -> int:
    """Merge `rows` into performance.jsonl, deduping by identity (new wins).

    Returns the number of rows added or updated. Ordering is stable: existing
    rows keep their position (updated in place), genuinely new rows append.
    """
    existing = read_rows()
    index = {_row_key(r): i for i, r in enumerate(existing)}
    changed = 0
    for r in rows:
        if not r:
            continue
        key = _row_key(r)
        if key in index:
            existing[index[key]] = {**existing[index[key]], **r}
        else:
            index[key] = len(existing)
            existing.append(r)
        changed += 1
    tmp = perf_path().with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in existing),
                   encoding="utf-8")
    tmp.replace(perf_path())
    return changed


# --------------------------------------------------------------------------- #
# Run-folder feature extraction (join analytics -> the run that made it)
# --------------------------------------------------------------------------- #
def _output_dir() -> Path:
    return _cfg.output_dir


def resolve_run_dir(run_id: str) -> Path | None:
    """A run_id is the folder name under output/. Tolerate a full path too."""
    if not run_id:
        return None
    p = Path(run_id)
    if p.is_dir():
        return p
    cand = _output_dir() / run_id
    if cand.is_dir():
        return cand
    # Last resort: a suffix/slug match against existing runs.
    for d in sorted(_output_dir().glob("*"), reverse=True):
        if d.is_dir() and (d.name == run_id or d.name.endswith(run_id)):
            return d
    return None


def _safe_json(path: Path) -> dict:
    try:
        return read_json(path) if path.exists() else {}
    except Exception:  # noqa: BLE001
        return {}


def classify_hook(hook: str) -> str:
    """Cheap, offline hook-shape label so we can correlate shape -> retention."""
    h = (hook or "").strip().lower()
    if not h:
        return "none"
    has_num = any(ch.isdigit() for ch in h) or "%" in h
    if h.startswith(("did you know", "ever wonder", "what if", "why do", "how do",
                     "have you ever")) or (h.endswith("?") and ("why" in h or "how" in h
                                                                or "what" in h)):
        return "stat-question" if has_num else "question"
    if h.split()[0] in {"stop", "never", "forget", "don't", "dont", "avoid", "quit"}:
        return "command"
    if has_num:
        return "stat-claim"
    if h.endswith("?"):
        return "question"
    return "claim"


def run_features(run: str | Path) -> dict | None:
    """Read an `output/<run_id>/` folder and distill the params to correlate.

    Returns None if the folder can't be found. Every field degrades to a sane
    default when a particular artifact is missing, so partial runs still ingest.
    """
    run_dir = resolve_run_dir(str(run))
    if run_dir is None:
        log.warning("[store] no run folder for run_id=%s", run)
        return None

    selection = _safe_json(run_dir / "selection.json")
    playbook = _safe_json(run_dir / "playbook.json")
    hooks = _safe_json(run_dir / "hooks.json")
    summary = _safe_json(run_dir / "summary.json")
    qc = _safe_json(run_dir / "qc_report.json")
    meta = _safe_json(run_dir / "metadata.json")

    pacing = playbook.get("pacing", {}) if isinstance(playbook, dict) else {}
    hook = hooks.get("winner") or summary.get("hook") or ""
    scenes = summary.get("scenes")

    return {
        "run_id": run_dir.name,
        "niche": selection.get("niche") or summary.get("niche"),
        "format": selection.get("format") or summary.get("format") or "short",
        "playbook_source": playbook.get("_source"),
        "target_seconds": selection.get("target_seconds"),
        "seconds_per_scene": pacing.get("seconds_per_scene"),
        "scene_count": scenes,
        "hook": hook,
        "hook_words": len(hook.split()) if hook else 0,
        "hook_style": classify_hook(hook),
        "qc_score": summary.get("qc_score") if summary.get("qc_score") is not None
        else qc.get("score"),
        "title_variants": summary.get("title_variants") or meta.get("title_variants") or [],
    }
