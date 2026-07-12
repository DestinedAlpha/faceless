"""Configuration loading: config.yaml + .env, with dotted access + env expansion."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root = the `faceless/` directory that contains config.yaml
ROOT = Path(__file__).resolve().parents[2]


class Config:
    """Thin wrapper over the parsed YAML with dotted `get` access."""

    def __init__(self, data: dict[str, Any], root: Path):
        self._data = data
        self.root = root

    def get(self, path: str, default: Any = None) -> Any:
        """Dotted lookup, e.g. cfg.get('providers.llm.gemini_model')."""
        node: Any = self._data
        for key in path.split("."):
            if isinstance(node, dict) and key in node:
                node = node[key]
            else:
                return default
        return node

    def __getitem__(self, path: str) -> Any:
        val = self.get(path, _MISSING)
        if val is _MISSING:
            raise KeyError(path)
        return val

    @property
    def data(self) -> dict[str, Any]:
        return self._data

    # --- resolved runtime paths -------------------------------------------
    @property
    def cache_dir(self) -> Path:
        d = self.root / self.get("runtime.cache_dir", "cache")
        d.mkdir(parents=True, exist_ok=True)
        return d

    @property
    def output_dir(self) -> Path:
        d = self.root / self.get("runtime.output_dir", "output")
        d.mkdir(parents=True, exist_ok=True)
        return d


_MISSING = object()
_CACHED: Config | None = None


def load_config(path: str | Path | None = None, reload: bool = False) -> Config:
    """Load config.yaml + .env once (cached). Pass reload=True to force."""
    global _CACHED
    if _CACHED is not None and not reload:
        return _CACHED

    root = ROOT
    load_dotenv(root / ".env")  # no-op if missing; keys just stay unset

    cfg_path = Path(path) if path else root / "config.yaml"
    with open(cfg_path, "r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}

    _CACHED = Config(data, root)
    return _CACHED


def env(name: str, default: str | None = None) -> str | None:
    """Fetch an env var (from .env or the environment). Empty string -> default."""
    val = os.environ.get(name, "")
    return val if val else default


def has_key(*names: str) -> bool:
    """True only if every named env var is present and non-empty."""
    return all(env(n) for n in names)
