"""AnthropicProvider 純函式測試 — 驗 cache_control 標記位置。

新慣例(2026-05-10):caller 保證 list 內每段都是 cacheable(volatile 內容
應由 caller 注入 user message),所以 _build_system_param 對每段都標
cache_control。空字串段跳過(API 拒收 cache_control on empty block)。
"""

from __future__ import annotations

from orion_agent.llm.anthropic_provider import _build_system_param


def test_string_system_passes_through() -> None:
    """str 直接回傳,不轉 blocks。"""
    assert _build_system_param("hello") == "hello"


def test_two_element_list_caches_both() -> None:
    """[static, session_stable] — 兩段都標 cache_control(2 個 bp)。"""
    out = _build_system_param(["static", "session_stable"])
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0] == {
        "type": "text",
        "text": "static",
        "cache_control": {"type": "ephemeral"},
    }
    assert out[1] == {
        "type": "text",
        "text": "session_stable",
        "cache_control": {"type": "ephemeral"},
    }


def test_three_element_list_caches_all() -> None:
    """3 段 — 全段都標 cache_control(3 個 bp)。"""
    out = _build_system_param(["a", "b", "c"])
    assert isinstance(out, list)
    assert all(
        isinstance(b, dict) and b.get("cache_control") == {"type": "ephemeral"}
        for b in out
    )


def test_single_element_list_caches_only_element() -> None:
    """單元素 — 標在唯一一段。"""
    out = _build_system_param(["only"])
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0] == {
        "type": "text",
        "text": "only",
        "cache_control": {"type": "ephemeral"},
    }


def test_empty_string_segments_skip_cache_control() -> None:
    """空字串段不標 cache_control(API 拒收)。"""
    out = _build_system_param(["static", ""])
    assert isinstance(out, list)
    assert out[0].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in out[1]


def test_empty_list_does_not_crash() -> None:
    """邊界:空 list 不應 crash。"""
    out = _build_system_param([])
    assert out == []
