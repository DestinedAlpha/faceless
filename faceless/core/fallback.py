"""Provider fallback: try adapters in order, return the first success.

Every layer (llm, images, tts, stock, subtitles) is a list of *providers* — small
callables that either return a result or raise. `try_providers` walks them in the
configured order, logging each failure, and only raises if *all* fail. This is what
makes the pipeline "works, not just errors": one dead API never breaks a run.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Generic, Sequence, TypeVar

from .log import get_logger

log = get_logger(__name__)

T = TypeVar("T")


class AllProvidersFailed(RuntimeError):
    def __init__(self, layer: str, errors: dict[str, str]):
        self.layer = layer
        self.errors = errors
        detail = "; ".join(f"{k}: {v}" for k, v in errors.items())
        super().__init__(f"All '{layer}' providers failed -> {detail}")


@dataclass
class Provider(Generic[T]):
    name: str
    fn: Callable[..., T]
    available: bool = True   # e.g. key present; skipped (not tried) if False


def try_providers(layer: str, providers: Sequence[Provider[T]], *args, **kwargs) -> T:
    """Try each *available* provider in order; return first success."""
    errors: dict[str, str] = {}
    tried = False
    for p in providers:
        if not p.available:
            log.debug("[%s] skip '%s' (unavailable)", layer, p.name)
            continue
        tried = True
        try:
            log.info("[%s] trying provider '%s'", layer, p.name)
            return p.fn(*args, **kwargs)
        except Exception as exc:  # noqa: BLE001 - we want to try the next one
            errors[p.name] = f"{type(exc).__name__}: {exc}"
            log.warning("[%s] provider '%s' failed: %s", layer, p.name, exc)
    if not tried:
        errors["(none)"] = "no providers available (missing keys?)"
    raise AllProvidersFailed(layer, errors)
