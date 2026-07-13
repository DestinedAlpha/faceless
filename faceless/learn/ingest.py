"""Ingest analytics into `memory/performance.jsonl`.

Two sources, one output. Every row joins real metrics to the run that produced
the video (by the `run_id` recorded at package time), plus the structural features
we want to correlate against performance.

  1. Manual (always available, zero deps): you paste metrics from YouTube Studio
     into `memory/metrics_inbox.jsonl` — one JSON object per line, each with at
     least a `run_id` and whatever of the METRIC_FIELDS you have. This is the
     path the UPLOAD_CHECKLIST.md points you to. Ingesting is idempotent and the
     inbox is archived (not deleted) after a successful pass.

  2. Automated (optional OAuth): `from_youtube()` lists your uploads, matches each
     back to a run_id, and pulls metrics via the Analytics API.

Public API:
    inbox_path() -> Path
    write_inbox_template(rows=None) -> Path
    from_inbox(*, archive=True) -> list[dict]
    from_youtube(*, max_results=None, lookback_days=None) -> list[dict]
"""
from __future__ import annotations

import json
from pathlib import Path

from ..core.config import load_config
from ..core.log import get_logger
from ..core.util import slugify
from . import store
from .store import METRIC_FIELDS

log = get_logger(__name__)
_cfg = load_config()


def inbox_path() -> Path:
    raw = _cfg.get("learn.inbox", "memory/metrics_inbox.jsonl")
    p = Path(raw)
    if not p.is_absolute():
        p = _cfg.root / p
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


def _merge_features(entry: dict) -> dict | None:
    """Turn one raw {run_id/video_id, metrics...} entry into a performance row.

    Metric fields may be given flat (as the checklist lists them) or nested under
    `metrics`. The run's structural features are pulled from its output/ folder.
    """
    run_id = (entry.get("run_id") or "").strip()
    feats = store.run_features(run_id) if run_id else None
    if run_id and feats is None:
        log.warning("[ingest] run_id '%s' has no output/ folder; keeping metrics only",
                    run_id)
    row: dict = dict(feats or {})
    if run_id:
        row["run_id"] = run_id

    # Which title/thumbnail variant did you actually publish?
    for k in ("video_id", "title_variant_used", "thumbnail_variant_used", "recorded_at"):
        if entry.get(k) is not None:
            row[k] = entry[k]
    # Resolve the chosen title text if we know the variant index.
    variants = row.get("title_variants") or []
    tvi = entry.get("title_variant_used")
    if isinstance(tvi, int) and 0 <= tvi < len(variants):
        row["title_used"] = variants[tvi]

    metrics = dict(store.metric_defaults())
    nested = entry.get("metrics") if isinstance(entry.get("metrics"), dict) else {}
    for k in METRIC_FIELDS:
        if k in entry and entry[k] is not None:
            metrics[k] = entry[k]
        elif k in nested and nested[k] is not None:
            metrics[k] = nested[k]
    # Accept a couple of friendly aliases people type by hand.
    aliases = {"avd": "average_view_duration", "avp": "average_view_percentage",
               "view_pct": "average_view_percentage", "ctr_pct": "ctr"}
    for alias, field in aliases.items():
        if entry.get(alias) is not None and metrics.get(field) is None:
            metrics[field] = entry[alias]
    row["metrics"] = metrics

    if not row.get("run_id") and not row.get("video_id"):
        log.warning("[ingest] entry has neither run_id nor video_id; skipping: %s",
                    json.dumps(entry)[:120])
        return None
    return row


def from_inbox(*, archive: bool = True) -> list[dict]:
    """Read the manual inbox, upsert rows, and (optionally) archive the inbox."""
    p = inbox_path()
    if not p.exists():
        log.info("[ingest] no inbox at %s (nothing to ingest manually)", p)
        return []
    rows: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith(("#", "//")):
            continue
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            log.warning("[ingest] skipping malformed inbox line: %s", line[:100])
            continue
        row = _merge_features(entry)
        if row:
            rows.append(row)
    if not rows:
        return []
    n = store.upsert_rows(rows)
    log.info("[ingest] manual: %d entries -> %d rows upserted", len(rows), n)
    if archive:
        archive_dir = p.parent / "inbox_archive"
        archive_dir.mkdir(parents=True, exist_ok=True)
        # Timestamp-free name (Date.now is unavailable in scripts elsewhere, and we
        # want determinism): sequence by count of existing archives.
        seq = len(list(archive_dir.glob("metrics_inbox_*.jsonl")))
        p.replace(archive_dir / f"metrics_inbox_{seq:03d}.jsonl")
    return rows


def _match_run_id(video_title: str) -> str | None:
    """Best-effort join of an uploaded video back to a run by slugified title.

    Reliable joins come from the run_id you record at upload time; this is only a
    convenience for videos uploaded straight from the kit without a manual note.
    """
    slug = slugify(video_title)
    if not slug:
        return None
    best = None
    for d in sorted(_cfg.output_dir.glob("*"), reverse=True):
        if not d.is_dir():
            continue
        # run_id looks like "<stamp>_<slug>"; compare the slug tail.
        tail = d.name.split("_", 1)[-1]
        if tail and (tail in slug or slug in tail):
            best = d.name
            break
    return best


def from_youtube(*, max_results: int | None = None,
                 lookback_days: int | None = None) -> list[dict]:
    """Pull recent uploads + metrics via OAuth and upsert them. []=unavailable."""
    from . import youtube_analytics as yt
    if not yt.available():
        log.info("[ingest] YouTube OAuth unavailable; use the manual inbox instead")
        return []
    try:
        creds = yt.authenticate()
        uploads = yt.list_uploads(int(max_results or _cfg.get("learn.max_backfill", 50)),
                                  creds=creds)
    except Exception as exc:  # noqa: BLE001
        log.warning("[ingest] YouTube pull failed: %s", exc)
        return []

    rows: list[dict] = []
    for up in uploads:
        run_id = _match_run_id(up.get("title", ""))
        try:
            metrics = yt.video_metrics(up["video_id"], lookback_days=lookback_days,
                                       creds=creds)
        except Exception as exc:  # noqa: BLE001
            log.warning("[ingest] metrics failed for %s: %s", up.get("video_id"), exc)
            metrics = store.metric_defaults()
        entry = {"run_id": run_id or "", "video_id": up["video_id"],
                 "title_yt": up.get("title"), "metrics": metrics}
        row = _merge_features(entry)
        if row:
            row.setdefault("title_used", up.get("title"))
            rows.append(row)
    if rows:
        n = store.upsert_rows(rows)
        log.info("[ingest] youtube: %d uploads -> %d rows upserted", len(uploads), n)
    return rows


# --------------------------------------------------------------------------- #
# Inbox template (so reporting back is copy/paste, not guesswork)
# --------------------------------------------------------------------------- #
def write_inbox_template(rows: list[dict] | None = None) -> Path:
    """Write/refresh the manual inbox with one prefilled stub per un-reported run.

    Each stub carries the run_id and null metric fields for you to fill from
    YouTube Studio. Runs already present in performance.jsonl are skipped.
    """
    p = inbox_path()
    if p.exists() and p.stat().st_size > 0:
        log.info("[ingest] inbox already exists at %s (leaving it)", p)
        return p
    reported = {r.get("run_id") for r in store.read_rows() if r.get("run_id")}
    stubs: list[dict] = []
    if rows is None:
        for d in sorted(_cfg.output_dir.glob("*"), reverse=True):
            if d.is_dir() and (d / "summary.json").exists() and d.name not in reported:
                stubs.append({"run_id": d.name})
    else:
        stubs = rows
    header = ("# metrics_inbox.jsonl — one JSON object per line. Fill the numbers\n"
              "# from YouTube Studio (~48h after upload), then run: python -m faceless\n"
              f"# learn. Metric fields: {', '.join(METRIC_FIELDS)}\n")
    lines = [header]
    for s in stubs[:20]:
        obj = {"run_id": s.get("run_id"), "title_variant_used": 0,
               "thumbnail_variant_used": 0, **store.metric_defaults()}
        lines.append(json.dumps(obj, ensure_ascii=False))
    p.write_text("\n".join(lines) + "\n", encoding="utf-8")
    log.info("[ingest] wrote inbox template with %d stub(s) -> %s", len(stubs), p)
    return p
