"""One-off backfill: seed the learn loop from your existing YouTube uploads.

Run once after granting OAuth consent to import historical uploads into
`memory/performance.jsonl`, then `python -m faceless learn` (or this script's
--reflect) distills them. Videos that predate the generator won't carry a run_id
(so they lack structural features), but their metrics still establish per-niche
retention/CTR baselines the reflection reasons against.

Usage:
    python scripts/backfill_analytics.py [--max N] [--reflect]

Entirely optional and free: needs the one-time Google OAuth consent (see
faceless/learn/youtube_analytics.py). With no OAuth configured it prints how to
set it up and exits 0 (nothing is required to start).
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from faceless.core.log import get_logger, setup_logging  # noqa: E402
from faceless.learn import ingest, reflect, store  # noqa: E402
from faceless.learn import youtube_analytics as yt  # noqa: E402

setup_logging("INFO")
log = get_logger("backfill")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Seed learn loop from past uploads")
    ap.add_argument("--max", type=int, default=50, help="max uploads to import")
    ap.add_argument("--reflect", action="store_true",
                    help="also distill learnings + patch playbooks after import")
    args = ap.parse_args(argv)

    if not yt.available():
        log.warning("YouTube OAuth is not configured — nothing to backfill.")
        print("\nTo enable automated backfill (free, one-time):\n"
              "  1. pip install google-auth-oauthlib google-api-python-client\n"
              "  2. Create a 'Desktop app' OAuth client at console.cloud.google.com,\n"
              "     enable the YouTube Data + Analytics APIs, download the JSON to\n"
              "     memory/client_secret.json\n"
              "  3. Re-run this script (a browser opens once to consent).\n\n"
              "Or skip OAuth entirely: paste metrics into memory/metrics_inbox.jsonl\n"
              "and run `python -m faceless learn`.")
        return 0

    rows = ingest.from_youtube(max_results=args.max)
    log.info("backfilled %d rows; performance.jsonl now has %d total",
             len(rows), len(store.read_rows()))
    if args.reflect:
        summary = reflect.reflect()
        print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
