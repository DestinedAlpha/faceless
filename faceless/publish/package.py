"""Packaging: turn a finished run into a paste-ready upload kit.

Writes `UPLOAD_CHECKLIST.md` into the run folder — the one file you open before
uploading. It collects the chosen title + A/B variants, the thumbnail variants to
pick from, the paste-ready description + tags, chapters (long-form), a best-time-to-post
hint, and — crucially for the Phase 6 learn loop — the stable `run_id` plus the exact
metrics fields to report back after the video has run. Everything degrades: missing
pieces just render as "—". This never renders or uploads anything; it only assembles.

Public API:
    write_checklist(run_dir, *, run_id, selection, script, metadata, summary,
                    thumbnails, qc_report, qc_post, hooks) -> Path
"""
from __future__ import annotations

from pathlib import Path

from ..core.log import get_logger

log = get_logger(__name__)

# Rough, niche-agnostic posting hint. Not analytics-driven yet (that's Phase 6);
# it's a sane default so the checklist isn't blank.
_POST_HINT = ("Shorts: post 11:00-13:00 or 18:00-21:00 local, when your audience is "
              "active. Long-form: 1-2h before your peak so it's indexed by prime time.")


def _fmt_list(items, bullet: str = "-") -> str:
    items = [str(i).strip() for i in (items or []) if str(i).strip()]
    return "\n".join(f"{bullet} {i}" for i in items) if items else "—"


def _fmt_chapters(chapters) -> str:
    rows = []
    for c in chapters or []:
        t, label = c.get("time", "").strip(), c.get("label", "").strip()
        if t and label:
            rows.append(f"{t} {label}")
    return "\n".join(rows) if rows else "—"


def _qc_line(qc_report: dict | None, qc_post: dict | None) -> str:
    pre = "—"
    if qc_report:
        pre = (f"{qc_report.get('score', '—')} / thr {qc_report.get('threshold', '—')} "
               f"({'PASS' if qc_report.get('passed') else 'FAIL'}"
               f"{', revised' if qc_report.get('revised') else ''})")
    post = "—"
    if qc_post:
        post = "PASS" if qc_post.get("passed") else f"FAIL {qc_post.get('issues')}"
    return f"- Pre-render QC: {pre}\n- Post-render QC: {post}"


def write_checklist(run_dir: Path, *, run_id: str, selection: dict, script: dict,
                    metadata: dict, summary: dict, thumbnails: list,
                    qc_report: dict | None = None, qc_post: dict | None = None,
                    hooks: dict | None = None) -> Path:
    run_dir = Path(run_dir)
    md = metadata or {}
    fmt = selection.get("format", "short")
    is_long = fmt != "short"
    video = summary.get("video")
    thumbs = [Path(t).name for t in (thumbnails or []) if t]

    titles = md.get("title_variants") or [md.get("title", "")]
    title_block = "\n".join(
        f"{i+1}. {t}{'   <- primary' if t == md.get('title') else ''}"
        for i, t in enumerate(titles))

    hook_block = "—"
    if hooks:
        hook_block = (f"- Primary: {hooks.get('winner', '—')}\n"
                      f"- A/B alt: {hooks.get('alt') or '—'}")

    chapters_section = ""
    if is_long:
        chapters_section = f"\n## Chapters (paste into description)\n```\n{_fmt_chapters(md.get('chapters'))}\n```\n"

    content = f"""# Upload checklist — {md.get('title', selection.get('topic', ''))}

**run_id:** `{run_id}`  ·  **niche:** {selection.get('niche')}  ·  **format:** {fmt}  \
·  **video:** {Path(video).name if video else '(!) NOT RENDERED'}

## 1. Pick a title (A/B)
{title_block}

## 2. Pick a thumbnail
{_fmt_list(thumbs)}
_(variant 0 is subject-forward when a clean cutout was available.)_

## 3. Hook used
{hook_block}

## 4. Description (paste as-is)
```
{md.get('description', '—')}
```

## 5. Tags
```
{", ".join(md.get('tags', []) or []) or '—'}
```
{chapters_section}
## 6. Best time to post
{_POST_HINT}

## 7. Quality gate
{_qc_line(qc_report, qc_post)}

## 8. After it runs — report back for the learn loop (Phase 6)
Once the video has ~48h of data, add ONE line to `memory/metrics_inbox.jsonl`
(fill numbers from YouTube Studio), then run `python -m faceless learn`:
```
{{"run_id": "{run_id}", "title_variant_used": 0, "thumbnail_variant_used": 0, "views": 0, "impressions": 0, "ctr": 0.0, "average_view_duration": 0.0, "average_view_percentage": 0.0, "retention_3s": 0.0, "likes": 0, "comments": 0, "subs_gained": 0}}
```
The loop joins this back to the run by `run_id`, appends to `memory/performance.jsonl`,
and (once a niche has enough samples) patches `playbooks/learned/<niche>.yaml`.

> Never auto-upload. You choose what goes live; the loop only reads analytics you report.
"""
    out = run_dir / "UPLOAD_CHECKLIST.md"
    out.write_text(content, encoding="utf-8")
    log.info("[package] wrote %s", out.name)
    return out
