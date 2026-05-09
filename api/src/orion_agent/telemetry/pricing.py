"""Per-token pricing wrapper — thin shim over `llm.catalog.find_pricing_by_model`.

`cost_tracker` only sees model names (not provider context), so this module does
the reverse lookup. Source data lives in `models.json` as USD per 1M tokens;
this shim divides by 1e6 to expose per-token rates as a `ModelPricing` dataclass
for backwards compatibility with cost_tracker.

Unknown / version-suffixed models prefix-match (e.g. `claude-sonnet-4-6-20251022`
→ `claude-sonnet-4-6`); no prefix match falls back to sonnet so cost calc never
crashes — `catalog.validate` is the right place to gate unknown models earlier.
"""

from __future__ import annotations

from dataclasses import dataclass

from orion_agent.llm.catalog import find_pricing_by_model, iter_all_entries


@dataclass(frozen=True)
class ModelPricing:
    """Per-token USD pricing for one model."""

    input_per_token: float
    output_per_token: float
    cache_creation_per_token: float
    """Cache write (Anthropic prompt-caching tier 1). 0 for providers without this concept."""
    cache_read_per_token: float
    """Cache hit (much cheaper than fresh input)."""


def _to_model_pricing(p: dict[str, float]) -> ModelPricing:
    return ModelPricing(
        input_per_token=p["input"] / 1e6,
        output_per_token=p["output"] / 1e6,
        cache_creation_per_token=p.get("cache_creation", 0.0) / 1e6,
        cache_read_per_token=p["cache_read"] / 1e6,
    )


def get_model_pricing(model: str) -> ModelPricing:
    p = find_pricing_by_model(model)
    if p is not None:
        return _to_model_pricing(dict(p))
    for e in iter_all_entries():
        if model.startswith(e["id"]):
            return _to_model_pricing(dict(e["pricing"]))
    fb = find_pricing_by_model("claude-sonnet-4-6")
    assert fb is not None, "claude-sonnet-4-6 missing from catalog — broken build"
    return _to_model_pricing(dict(fb))


__all__ = ["ModelPricing", "get_model_pricing"]
