"""Unit tests for orion_model.stt_pricing — thin shim over stt_catalog。"""

from __future__ import annotations

from orion_model import stt_catalog, stt_pricing


def test_get_per_minute_price_known() -> None:
    stt_catalog.reset_cache_for_tests()
    price = stt_pricing.get_per_minute_price("openai", "gpt-4o-mini-transcribe")
    assert price is not None and price > 0


def test_get_per_minute_price_unknown() -> None:
    stt_catalog.reset_cache_for_tests()
    assert stt_pricing.get_per_minute_price("openai", "nonexistent") is None
    assert stt_pricing.get_per_minute_price("nonexistent", "anything") is None


def test_compute_cost_basic() -> None:
    stt_catalog.reset_cache_for_tests()
    # gpt-4o-mini-transcribe @ $0.003/min × 60s (1min) = $0.003
    cost = stt_pricing.compute_stt_cost("openai", "gpt-4o-mini-transcribe", 60.0)
    assert cost is not None
    assert abs(cost - 0.003) < 1e-9


def test_compute_cost_short_audio() -> None:
    stt_catalog.reset_cache_for_tests()
    # 30s 半分鐘 → 0.5 × $0.006 = $0.003 (for whisper-1)
    cost = stt_pricing.compute_stt_cost("openai", "whisper-1", 30.0)
    assert cost is not None
    assert abs(cost - 0.003) < 1e-9


def test_compute_cost_none_duration() -> None:
    stt_catalog.reset_cache_for_tests()
    assert stt_pricing.compute_stt_cost("openai", "whisper-1", None) is None
    assert stt_pricing.compute_stt_cost("openai", "whisper-1", 0) is None
    assert stt_pricing.compute_stt_cost("openai", "whisper-1", -1) is None


def test_compute_cost_unknown_model() -> None:
    stt_catalog.reset_cache_for_tests()
    # unknown model — caller wants 'unknown' signal, not crash
    assert stt_pricing.compute_stt_cost("openai", "nonexistent", 60.0) is None
