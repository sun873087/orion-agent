"""LLM 定價表 — per-token USD。

對應 spec § 5.6。2026 年 5 月公告價(per token,非 per million)。
未列模型 fallback 到 sonnet 定價(避免 cost=0 假象)。
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ModelPricing:
    """單一模型的 per-token USD 定價。"""

    input_per_token: float
    output_per_token: float
    cache_creation_per_token: float
    """寫 cache(prompt caching tier 1)"""
    cache_read_per_token: float
    """讀 cache hit(便宜很多)"""


# 2026-05 公告價 / per-million ÷ 1e6:
PRICING_TABLE: dict[str, ModelPricing] = {
    # Claude 4.x 系列
    "claude-opus-4-7": ModelPricing(
        input_per_token=15e-6,
        output_per_token=75e-6,
        cache_creation_per_token=18.75e-6,
        cache_read_per_token=1.5e-6,
    ),
    "claude-sonnet-4-6": ModelPricing(
        input_per_token=3e-6,
        output_per_token=15e-6,
        cache_creation_per_token=3.75e-6,
        cache_read_per_token=0.3e-6,
    ),
    "claude-haiku-4-5": ModelPricing(
        input_per_token=1e-6,
        output_per_token=5e-6,
        cache_creation_per_token=1.25e-6,
        cache_read_per_token=0.1e-6,
    ),
    # OpenAI 對照
    "gpt-4o": ModelPricing(
        input_per_token=2.5e-6,
        output_per_token=10e-6,
        cache_creation_per_token=2.5e-6,
        cache_read_per_token=1.25e-6,
    ),
    "gpt-4o-mini": ModelPricing(
        input_per_token=0.15e-6,
        output_per_token=0.6e-6,
        cache_creation_per_token=0.15e-6,
        cache_read_per_token=0.075e-6,
    ),
}


_DEFAULT = PRICING_TABLE["claude-sonnet-4-6"]


def get_model_pricing(model: str) -> ModelPricing:
    """找最匹配的 pricing(處理 `-20251022` 之類版本後綴)。"""
    if model in PRICING_TABLE:
        return PRICING_TABLE[model]
    # prefix match(例:`claude-sonnet-4-6-20251022` → `claude-sonnet-4-6`)
    for key, pricing in PRICING_TABLE.items():
        if model.startswith(key):
            return pricing
    return _DEFAULT
