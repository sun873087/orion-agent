"""Per-(provider, model) pricing — thin shim over `catalog.get_pricing`.

Pricing data lives in `models.json` (USD per 1M tokens). Provider `estimate_cost`
methods call `get_pricing(provider, model)` here. Unknown (provider, model)
falls back to the cheapest model of that provider so cost never crashes —
catalog.validate is the right place to gate "unknown model" earlier.
"""

from __future__ import annotations

from orion_model.catalog import get_pricing as _catalog_get_pricing

# Fallback when (provider, model) isn't in the catalog. Kept conservative —
# we'd rather slightly under-report than crash a session.
_FALLBACK_BY_PROVIDER = {
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-5",
}


def get_pricing(provider: str, model: str) -> dict[str, float]:
    """Returns {input, output, cache_read[, cache_creation]} — USD per 1M tokens."""
    p = _catalog_get_pricing(provider, model)
    if p is not None:
        return dict(p)
    fallback = _FALLBACK_BY_PROVIDER.get(provider)
    if fallback is not None:
        fb = _catalog_get_pricing(provider, fallback)
        if fb is not None:
            return dict(fb)
    return {"input": 0.0, "output": 0.0, "cache_read": 0.0}
