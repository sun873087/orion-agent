"""SessionCostTracker — record / total_cost / cache_hit_ratio + global registry。"""

from __future__ import annotations

import pytest

from orion_sdk.telemetry.cost_tracker import (
    SessionCostTracker,
    get_or_create_tracker,
    get_session_summary,
    reset_trackers,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_trackers()


def test_record_accumulates() -> None:
    t = SessionCostTracker(session_id="s1")
    t.record(model="claude-sonnet-4-6", input_tokens=100, output_tokens=50)
    t.record(model="claude-sonnet-4-6", input_tokens=200, output_tokens=80)
    m = t.by_model["claude-sonnet-4-6"]
    assert m.input_tokens == 300
    assert m.output_tokens == 130


def test_total_cost_uses_pricing() -> None:
    t = SessionCostTracker(session_id="s1")
    # sonnet:input 3e-6 / output 15e-6
    t.record(model="claude-sonnet-4-6", input_tokens=1_000_000, output_tokens=100_000)
    expected = 1_000_000 * 3e-6 + 100_000 * 15e-6
    assert abs(t.total_cost_usd() - expected) < 1e-9


def test_total_cost_multi_model() -> None:
    t = SessionCostTracker(session_id="s1")
    t.record(model="claude-sonnet-4-6", input_tokens=100, output_tokens=10)
    t.record(model="claude-haiku-4-5", input_tokens=200, output_tokens=20)
    cost = t.total_cost_usd()
    assert cost > 0
    # sonnet + haiku 都計入
    assert "claude-sonnet-4-6" in t.by_model
    assert "claude-haiku-4-5" in t.by_model


def test_cache_hit_ratio() -> None:
    t = SessionCostTracker(session_id="s1")
    t.record(
        model="claude-sonnet-4-6",
        input_tokens=200,
        cache_creation_tokens=100,
        cache_read_tokens=700,
    )
    # total input = 1000,cache_read = 700 → 0.7
    assert abs(t.cache_hit_ratio() - 0.7) < 1e-9


def test_cache_hit_ratio_zero_total() -> None:
    t = SessionCostTracker(session_id="s1")
    assert t.cache_hit_ratio() == 0.0


def test_summary_has_expected_keys() -> None:
    t = SessionCostTracker(session_id="s1", user_id="u1")
    t.record(model="claude-sonnet-4-6", input_tokens=1, output_tokens=1)
    s = t.summary()
    assert s["session_id"] == "s1"
    assert s["user_id"] == "u1"
    assert "total_cost_usd" in s
    assert "cache_hit_ratio" in s
    assert "by_model" in s


def test_global_registry_get_or_create() -> None:
    a = get_or_create_tracker("s1", "u1")
    b = get_or_create_tracker("s1")
    assert a is b


def test_global_registry_lazy_user_id_fill() -> None:
    a = get_or_create_tracker("s1")
    assert a.user_id is None
    b = get_or_create_tracker("s1", "u1")
    assert b is a
    assert b.user_id == "u1"


def test_get_session_summary_missing() -> None:
    assert get_session_summary("nope") is None


def test_get_session_summary_present() -> None:
    t = get_or_create_tracker("s1", "u1")
    t.record(model="claude-sonnet-4-6", input_tokens=10, output_tokens=5)
    s = get_session_summary("s1")
    assert s is not None
    assert s["session_id"] == "s1"
