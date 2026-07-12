"""Central logging via rich. Import `get_logger(__name__)` everywhere."""
from __future__ import annotations

import logging
import os

from rich.console import Console
from rich.logging import RichHandler

console = Console()
_CONFIGURED = False


def setup_logging(level: str | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    lvl = (level or os.environ.get("FACELESS_LOG_LEVEL") or "INFO").upper()
    logging.basicConfig(
        level=lvl,
        format="%(message)s",
        datefmt="[%X]",
        handlers=[RichHandler(console=console, rich_tracebacks=True,
                              show_path=False, markup=True)],
    )
    # Quiet noisy libraries.
    for noisy in ("httpx", "httpcore", "urllib3", "PIL"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
