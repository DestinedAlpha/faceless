"""LLM client: Gemini 2.5 Flash primary, Groq Llama 3.3 70B fallback.

Exposes two calls:
  - complete(prompt, system=None) -> str
  - complete_json(prompt, schema=None, system=None) -> dict/list

Both walk the provider order from config (providers.llm.order) via the shared
fallback wrapper. JSON mode uses Gemini's native responseSchema; for Groq we ask
for a JSON object and parse defensively.
"""
from __future__ import annotations

import json
import re
from typing import Any

from ..core import http
from ..core.config import env, load_config
from ..core.fallback import Provider, try_providers
from ..core.log import get_logger

log = get_logger(__name__)
_cfg = load_config()

GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


# --------------------------------------------------------------------------- #
# Provider implementations
# --------------------------------------------------------------------------- #
def _gemini(prompt: str, *, system: str | None, schema: dict | None) -> str:
    key = env("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")
    model = _cfg.get("providers.llm.gemini_model", "gemini-2.5-flash")
    gen: dict[str, Any] = {"temperature": 0.9, "maxOutputTokens": 8192}
    if schema is not None:
        gen["responseMimeType"] = "application/json"
        gen["responseSchema"] = _to_gemini_schema(schema)
    body: dict[str, Any] = {
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": gen,
    }
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    data = http.post_json(
        GEMINI_URL.format(model=model),
        params={"key": key},
        json=body,
        cache=False,
        headers={"Content-Type": "application/json"},
    )
    try:
        return data["candidates"][0]["content"]["parts"][0]["text"]
    except (KeyError, IndexError) as exc:
        raise RuntimeError(f"Gemini unexpected response: {json.dumps(data)[:300]}") from exc


def _groq(prompt: str, *, system: str | None, schema: dict | None) -> str:
    key = env("GROQ_API_KEY")
    if not key:
        raise RuntimeError("GROQ_API_KEY not set")
    model = _cfg.get("providers.llm.groq_model", "llama-3.3-70b-versatile")
    messages = []
    sys_text = system or ""
    if schema is not None:
        sys_text += ("\nRespond ONLY with a single valid JSON value matching this "
                     f"JSON schema (no prose, no markdown fences):\n{json.dumps(schema)}")
    if sys_text.strip():
        messages.append({"role": "system", "content": sys_text.strip()})
    messages.append({"role": "user", "content": prompt})
    body: dict[str, Any] = {"model": model, "messages": messages, "temperature": 0.9}
    if schema is not None:
        body["response_format"] = {"type": "json_object"}
    data = http.post_json(
        GROQ_URL,
        json=body,
        cache=False,
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
    )
    return data["choices"][0]["message"]["content"]


def _providers(schema: dict | None):
    order = _cfg.get("providers.llm.order", ["gemini", "groq"])
    impls = {
        "gemini": Provider("gemini", lambda p, system: _gemini(p, system=system, schema=schema),
                           available=bool(env("GEMINI_API_KEY"))),
        "groq": Provider("groq", lambda p, system: _groq(p, system=system, schema=schema),
                         available=bool(env("GROQ_API_KEY"))),
    }
    return [impls[name] for name in order if name in impls]


# --------------------------------------------------------------------------- #
# Public API
# --------------------------------------------------------------------------- #
def complete(prompt: str, *, system: str | None = None) -> str:
    return try_providers("llm", _providers(None), prompt, system)


def complete_json(prompt: str, *, schema: dict | None = None,
                  system: str | None = None) -> Any:
    text = try_providers("llm", _providers(schema), prompt, system)
    return _extract_json(text)


def available() -> bool:
    return bool(env("GEMINI_API_KEY") or env("GROQ_API_KEY"))


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _extract_json(text: str) -> Any:
    """Parse JSON from a model response, tolerating markdown fences / stray prose."""
    text = text.strip()
    # Strip ```json ... ``` fences if present.
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Last resort: grab the outermost {...} or [...] span.
    for open_c, close_c in (("{", "}"), ("[", "]")):
        start, end = text.find(open_c), text.rfind(close_c)
        if 0 <= start < end:
            try:
                return json.loads(text[start:end + 1])
            except json.JSONDecodeError:
                continue
    raise ValueError(f"Could not parse JSON from LLM output: {text[:300]}")


# Gemini's responseSchema is an OpenAPI subset. Our schemas are simple enough that
# they pass through; we just drop keys Gemini rejects (additionalProperties, $schema).
def _to_gemini_schema(schema: dict) -> dict:
    drop = {"additionalProperties", "$schema", "title", "default", "examples"}

    def clean(node: Any) -> Any:
        if isinstance(node, dict):
            return {k: clean(v) for k, v in node.items() if k not in drop}
        if isinstance(node, list):
            return [clean(v) for v in node]
        return node

    return clean(schema)
