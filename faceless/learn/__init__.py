"""The analytics learning loop (Phase 6): pull -> ingest -> reflect -> patch.

Manual-upload-only by design: this package *reads* the performance of videos you
uploaded yourself and *updates the playbooks* — it never posts anything. Two ways
in: paste metrics from YouTube Studio into `memory/metrics_inbox.jsonl` (zero deps),
or grant a one-time Google OAuth consent to pull them automatically.

Public API:
    run_learn(*, pull=False, reflect=True, backfill=0, template=False,
              min_samples=None, use_llm=True) -> dict
"""
from __future__ import annotations

from ..core.log import get_logger
from . import ingest as _ingest
from . import reflect as _reflect
from . import store

log = get_logger(__name__)

__all__ = ["run_learn", "ingest", "reflect", "store"]
ingest = _ingest
reflect = _reflect


def run_learn(*, pull: bool = False, reflect: bool = True, backfill: int = 0,
              template: bool = False, min_samples: int | None = None,
              use_llm: bool = True) -> dict:
    """Run the learn loop end to end.

    - `template`: (re)write the manual inbox with a stub per un-reported run.
    - always ingest the manual inbox if present.
    - `pull`/`backfill`: also pull metrics via OAuth (backfill = max uploads).
    - `reflect`: distill learnings.md + patch playbook overlays.
    """
    result: dict = {"ingested": 0, "source": []}

    if template:
        result["inbox"] = str(_ingest.write_inbox_template())

    manual = _ingest.from_inbox(archive=True)
    if manual:
        result["ingested"] += len(manual)
        result["source"].append("inbox")

    if pull or backfill:
        auto = _ingest.from_youtube(max_results=backfill or None)
        if auto:
            result["ingested"] += len(auto)
            result["source"].append("youtube")

    result["rows_total"] = len(store.read_rows())

    if reflect:
        result["reflect"] = _reflect.reflect(min_samples=min_samples, use_llm=use_llm)

    log.info("[learn] ingested=%d rows_total=%d", result["ingested"],
             result["rows_total"])
    return result
