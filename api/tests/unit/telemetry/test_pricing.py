"""Pricing table — known model 直接 lookup,版本後綴 prefix match,unknown fallback。"""

from __future__ import annotations

from orion_agent.telemetry.pricing import PRICING_TABLE, get_model_pricing


def test_known_model() -> None:
    p = get_model_pricing("claude-sonnet-4-6")
    assert p.input_per_token == 3e-6


def test_version_suffix_prefix_match() -> None:
    p = get_model_pricing("claude-sonnet-4-6-20251022")
    assert p is PRICING_TABLE["claude-sonnet-4-6"]


def test_unknown_falls_back() -> None:
    p = get_model_pricing("not-a-real-model")
    # fallback = sonnet
    assert p is PRICING_TABLE["claude-sonnet-4-6"]


def test_haiku_cheaper_than_sonnet_cheaper_than_opus() -> None:
    h = get_model_pricing("claude-haiku-4-5")
    s = get_model_pricing("claude-sonnet-4-6")
    o = get_model_pricing("claude-opus-4-7")
    assert h.input_per_token < s.input_per_token < o.input_per_token
    assert h.output_per_token < s.output_per_token < o.output_per_token
