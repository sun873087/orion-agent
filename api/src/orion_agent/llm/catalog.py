"""Model catalog — single source of truth for per-(provider, model) attributes.

Loaded at startup from packaged `models.json` via `importlib.resources` (always
present — no built-in Python fallback). `ORION_MODELS_FILE` env overrides for prod
deployments. Strict validation on (provider, model) pairs blocks UI clients from
DevTools-injecting unknown models.

Schema (all fields except cache_creation are required per model):

{
  "providers": [
    {
      "id": "anthropic",
      "label": "Anthropic",
      "models": [
        {
          "id": "claude-sonnet-4-6",
          "label": "Claude Sonnet 4.6",
          "max_output_tokens": 64000,
          "max_context_tokens": 200000,
          "supports_reasoning": false,
          "pricing": {
            "input": 3.0,
            "output": 15.0,
            "cache_read": 0.30,
            "cache_creation": 3.75
          }
        }
      ]
    }
  ]
}

Pricing is USD per 1M tokens (input/output/cache_read required;
cache_creation optional — Anthropic-only concept).
"""

from __future__ import annotations

import json
import logging
import os
from functools import cache
from importlib.resources import files
from pathlib import Path
from typing import TypedDict

_log = logging.getLogger(__name__)


class Pricing(TypedDict, total=False):
    input: float
    output: float
    cache_read: float
    cache_creation: float  # optional — only Anthropic models set this


class ModelEntry(TypedDict):
    id: str
    label: str
    max_output_tokens: int
    max_context_tokens: int
    supports_reasoning: bool
    pricing: Pricing


_PACKAGED_RESOURCE = files("orion_agent.llm").joinpath("models.json")


def _resolve_override_path() -> Path | None:
    raw = os.environ.get("ORION_MODELS_FILE")
    if raw:
        return Path(raw).expanduser()
    return None


def _parse_pricing(raw: object) -> Pricing | None:
    if not isinstance(raw, dict):
        return None
    out: Pricing = {}
    for key in ("input", "output", "cache_read"):
        v = raw.get(key)
        if not isinstance(v, (int, float)):
            return None
        out[key] = float(v)  # type: ignore[literal-required]
    cc = raw.get("cache_creation")
    if isinstance(cc, (int, float)):
        out["cache_creation"] = float(cc)
    return out


def _parse_config(data: object) -> tuple[dict[str, list[ModelEntry]], dict[str, str]] | None:
    if not isinstance(data, dict):
        return None
    providers_raw = data.get("providers")
    if not isinstance(providers_raw, list):
        return None
    models: dict[str, list[ModelEntry]] = {}
    labels: dict[str, str] = {}
    for p in providers_raw:
        if not isinstance(p, dict):
            return None
        pid = p.get("id")
        plabel = p.get("label")
        models_raw = p.get("models")
        if not isinstance(pid, str) or not isinstance(models_raw, list):
            return None
        labels[pid] = plabel if isinstance(plabel, str) else pid
        entries: list[ModelEntry] = []
        for m in models_raw:
            if not isinstance(m, dict):
                return None
            mid = m.get("id")
            mlabel = m.get("label")
            mmax_out = m.get("max_output_tokens")
            mmax_ctx = m.get("max_context_tokens")
            msupports_reasoning = m.get("supports_reasoning", False)
            mpricing_raw = m.get("pricing")
            if not isinstance(mid, str):
                return None
            if not isinstance(mmax_out, int) or mmax_out < 1:
                return None
            if not isinstance(mmax_ctx, int) or mmax_ctx < 1:
                return None
            pricing = _parse_pricing(mpricing_raw)
            if pricing is None:
                return None
            entries.append(
                {
                    "id": mid,
                    "label": mlabel if isinstance(mlabel, str) else mid,
                    "max_output_tokens": mmax_out,
                    "max_context_tokens": mmax_ctx,
                    "supports_reasoning": bool(msupports_reasoning),
                    "pricing": pricing,
                }
            )
        models[pid] = entries
    return models, labels


def _read_packaged() -> tuple[dict[str, list[ModelEntry]], dict[str, str]]:
    raw = json.loads(_PACKAGED_RESOURCE.read_text(encoding="utf-8"))
    parsed = _parse_config(raw)
    if parsed is None:
        raise RuntimeError(
            "packaged models.json failed schema validation — this is a build-time bug",
        )
    return parsed


@cache
def _load() -> tuple[dict[str, list[ModelEntry]], dict[str, str]]:
    """Load catalog. Override path takes priority; otherwise use packaged JSON."""
    override = _resolve_override_path()
    if override is not None:
        if not override.is_file():
            _log.warning(
                "ORION_MODELS_FILE=%s not found — falling back to packaged catalog",
                override,
            )
            return _read_packaged()
        try:
            raw = json.loads(override.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            _log.warning("failed to load %s (%s) — falling back to packaged", override, e)
            return _read_packaged()
        parsed = _parse_config(raw)
        if parsed is None:
            _log.warning("invalid schema in %s — falling back to packaged", override)
            return _read_packaged()
        _log.info("loaded models config from override %s", override)
        return parsed
    return _read_packaged()


def _models() -> dict[str, list[ModelEntry]]:
    return _load()[0]


def _labels() -> dict[str, str]:
    return _load()[1]


def _entry(provider: str, model: str) -> ModelEntry | None:
    entries = _models().get(provider)
    if entries is None:
        return None
    for e in entries:
        if e["id"] == model:
            return e
    return None


def validate(provider: str, model: str) -> bool:
    """Strict (provider, model) check — no prefix fallback."""
    return _entry(provider, model) is not None


def get_max_output_tokens(provider: str, model: str) -> int | None:
    e = _entry(provider, model)
    return e["max_output_tokens"] if e else None


def get_max_context_tokens(provider: str, model: str) -> int | None:
    e = _entry(provider, model)
    return e["max_context_tokens"] if e else None


def get_supports_reasoning(provider: str, model: str) -> bool:
    """Whether this model supports reasoning blocks (Claude thinking / OpenAI o-series)."""
    e = _entry(provider, model)
    return e["supports_reasoning"] if e else False


def get_pricing(provider: str, model: str) -> Pricing | None:
    """Returns pricing dict (USD per 1M tokens) or None if unknown."""
    e = _entry(provider, model)
    return dict(e["pricing"]) if e else None  # type: ignore[return-value]


def find_pricing_by_model(model: str) -> Pricing | None:
    """Reverse lookup — used by cost_tracker which only has model name, not provider.

    Scans all providers; first match wins. Model names don't collide across
    Anthropic (claude-*) and OpenAI (gpt-*/o*), so this is unambiguous in practice.
    """
    for entries in _models().values():
        for e in entries:
            if e["id"] == model:
                return dict(e["pricing"])  # type: ignore[return-value]
    return None


def iter_all_entries() -> list[ModelEntry]:
    """Flat list of every catalog entry across providers — for prefix-match callers."""
    out: list[ModelEntry] = []
    for entries in _models().values():
        out.extend(entries)
    return out


def list_catalog() -> dict[str, object]:
    """For GET /models — caller decides `available` / `default`."""
    models = _models()
    labels = _labels()
    return {
        "providers": [
            {
                "id": p,
                "label": labels.get(p, p),
                "models": [dict(e) for e in entries],
            }
            for p, entries in models.items()
        ],
    }


def reset_cache_for_tests() -> None:
    """Clear @cache so monkeypatched ORION_MODELS_FILE takes effect."""
    _load.cache_clear()


__all__ = [
    "ModelEntry",
    "Pricing",
    "find_pricing_by_model",
    "get_max_context_tokens",
    "get_max_output_tokens",
    "get_pricing",
    "get_supports_reasoning",
    "iter_all_entries",
    "list_catalog",
    "reset_cache_for_tests",
    "validate",
]
