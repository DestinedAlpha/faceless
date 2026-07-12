"""CLI: `python -m faceless [command] [options]`.

Commands:
  run        (default) full pipeline: trends -> ... -> rendered mp4
  trends     just discover + print ranked topics (no generation)
  plan       trends -> select -> script, print it (no assets/render)

Options:
  --no-synthetic   fail instead of using the offline synthetic trend pool
  --skip-render    build video_spec.json + all assets but don't invoke Remotion
  --skip-stock     skip stock B-roll even if a key is present (AI stills only)
  --log LEVEL      DEBUG|INFO|WARNING|ERROR
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


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="faceless",
                                     description="Trend-driven faceless video generator")
    parser.add_argument("command", nargs="?", default="run",
                        choices=["run", "trends", "plan"])
    parser.add_argument("--no-synthetic", action="store_true")
    parser.add_argument("--skip-render", action="store_true")
    parser.add_argument("--skip-stock", action="store_true")
    parser.add_argument("--log", default=None)
    args = parser.parse_args(argv)

    setup_logging(args.log)

    dispatch = {"run": _cmd_run, "trends": _cmd_trends, "plan": _cmd_plan}
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
