"""Per-provider per-model 定價(USD per 1M tokens)。

數據來源:Anthropic / OpenAI 官方文件,2026-05 月份。
Phase 9(cost tracker)的 estimate_cost 用此表計算。

每個 model 的 dict 都是 {input, output, cache_read} ± cache_creation(僅 Anthropic)。
"""

from __future__ import annotations

PRICING: dict[str, dict[str, dict[str, float]]] = {
    "anthropic": {
        "claude-opus-4-7": {
            "input": 15.0,
            "output": 75.0,
            "cache_creation": 18.75,
            "cache_read": 1.50,
        },
        "claude-sonnet-4-6": {
            "input": 3.0,
            "output": 15.0,
            "cache_creation": 3.75,
            "cache_read": 0.30,
        },
        "claude-haiku-4-5": {
            "input": 1.0,
            "output": 5.0,
            "cache_creation": 1.25,
            "cache_read": 0.10,
        },
    },
    "openai": {
        "gpt-5.4": {
            "input": 5.0,
            "output": 20.0,
            "cache_read": 1.25,
        },
        "gpt-5": {
            "input": 2.5,
            "output": 10.0,
            "cache_read": 0.625,
        },
        "gpt-5-mini": {
            "input": 0.25,
            "output": 1.0,
            "cache_read": 0.0625,
        },
        "gpt-4o": {
            "input": 2.5,
            "output": 10.0,
            "cache_read": 1.25,
        },
        "gpt-4o-mini": {
            "input": 0.15,
            "output": 0.60,
            "cache_read": 0.075,
        },
        "o3": {
            "input": 5.0,
            "output": 20.0,
            "cache_read": 1.25,
        },
    },
}


def get_pricing(provider: str, model: str) -> dict[str, float]:
    """取對應 model 的定價。找不到 → fallback 到 sonnet/gpt-5 預設。"""
    provider_pricing = PRICING.get(provider, {})
    if model in provider_pricing:
        return dict(provider_pricing[model])
    # Prefix match(處理版本後綴變動)
    for key, p in provider_pricing.items():
        if model.startswith(key):
            return dict(p)
    # Fallback
    if provider == "anthropic":
        return dict(PRICING["anthropic"]["claude-sonnet-4-6"])
    return dict(PRICING["openai"]["gpt-5"])
