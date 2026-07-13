"""CLI: `python -m faceless [command] [options]`.

Commands:
  run        (default) full pipeline: trends -> ... -> rendered mp4
  trends     just discover + print ranked topics (no generation)
  plan       trends -> select -> script, print it (no assets/render)
  learn      ingest reported analytics -> distill learnings -> patch playbooks

Options:
  --no-synthetic   fail instead of using the offline synthetic trend pool
  --skip-render    build video_spec.json + all assets but don't invoke Remotion
  --skip-stock     skip stock B-roll even if a key is present (AI stills only)
  --log LEVEL      DEBUG|INFO|WARNING|ERROR

Learn-only options:
  --pull           also pull metrics via YouTube OAuth (needs one-time consent)
  --backfill N     pull up to N past uploads via OAuth to seed memory
  --template       (re)write memory/metrics_inbox.jsonl with a stub per un-reported run
  --no-reflect     ingest only; skip distillation + playbook patching
  --min-samples N  override per-niche samples required before patching
"""
from __future__ import annotations

import argparse
import json
import sys

from .core.log import get_logger, setup_logging

log = get_logger(__name__)


def _cmd_trends(args) -> int:
    from .trends.finder import find_topics
    topics = find_topics(allow_synthetic=not args.no_synthetic)
    for i, t in enumerate(topics):
        print(f"{i+1:2d}. score={t.score:.3f} sources={sorted(t.sources)} "
              f"size={t.size} :: {t.label}")
    return 0 if topics else 1


def _cmd_plan(args) -> int:
    from .plan import mastery
    from .plan.script import write_script
    from .plan.selector import select
    from .trends.finder import find_topics
    topics = find_topics(allow_synthetic=not args.no_synthetic)
    if not topics:
        log.error("no topics")
        return 1
    selection = select(topics)
    playbook = mastery.get_playbook(selection["niche"], topics)
    script = write_script(selection, playbook)
    print(json.dumps({"selection": selection, "playbook": playbook, "script": script},
                     indent=2, ensure_ascii=False))
    return 0


def _cmd_run(args) -> int:
    from .pipeline import run
    summary = run(
        allow_synthetic=not args.no_synthetic,
        skip_render=args.skip_render,
        skip_stock=args.skip_stock,
    )
    print("\n" + json.dumps(summary, indent=2, ensure_ascii=False))
    return 0 if summary.get("video") or args.skip_render else 2


def _cmd_learn(args) -> int:
    from .learn import run_learn
    result = run_learn(
        pull=args.pull,
        backfill=args.backfill,
        template=args.template,
        reflect=not args.no_reflect,
        min_samples=args.min_samples,
    )
    print("\n" + json.dumps(result, indent=2, ensure_ascii=False))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faceless",
                                     description="Trend-driven faceless video generator")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "trends", "plan", "learn"])
    parser.add_argument("--no-synthetic", action="store_true")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--skip-stock", action="store_true")
    parser.add_argument("--log", default=None)
    # learn-only
    parser.add_argument("--pull", action="store_true",
                        help="learn: also pull metrics via YouTube OAuth")
    parser.add_argument("--backfill", type=int, default=0,
                        help="learn: pull up to N past uploads via OAuth to seed memory")
    parser.add_argument("--template", action="store_true",
                        help="learn: (re)write memory/metrics_inbox.jsonl stubs")
    parser.add_argument("--no-reflect", action="store_true",
                        help="learn: ingest only; skip distillation + patching")
    parser.add_argument("--min-samples", type=int, default=None,
                        help="learn: override per-niche samples required before patching")
    args = parser.parse_args(argv)

    setup_logging(args.log)

    dispatch = {"run": _cmd_run, "trends": _cmd_trends, "plan": _cmd_plan,
                "learn": _cmd_learn}
    try:
        return dispatch[args.command](args)
    except KeyboardInterrupt:
        log.warning("interrupted")
        return 130
    except Exception as exc:  # noqa: BLE001
        log.exception("fatal: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
