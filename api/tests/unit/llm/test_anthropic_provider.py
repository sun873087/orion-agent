"""AnthropicProvider 純函式測試 — 主要驗 cache_control 標記位置。"""

from __future__ import annotations

from orion_agent.llm.anthropic_provider import _build_system_param


def test_string_system_passes_through() -> None:
    """str 直接回傳,不轉 blocks。"""
    assert _build_system_param("hello") == "hello"


def test_two_element_list_caches_first() -> None:
    """[static, dynamic] — cache_control 應該標在 list[0](倒數第二段)。"""
    out = _build_system_param(["static", "dynamic"])
    assert isinstance(out, list)
    assert len(out) == 2
    assert out[0] == {
        "type": "text",
        "text": "static",
        "cache_control": {"type": "ephemeral"},
    }
    assert out[1] == {"type": "text", "text": "dynamic"}
    assert "cache_control" not in out[1]


def test_three_element_list_caches_second_to_last() -> None:
    """3 段 — cache_control 在 list[1](倒數第二)。"""
    out = _build_system_param(["a", "b", "c"])
    assert isinstance(out, list)
    assert "cache_control" not in out[0]
    assert out[1].get("cache_control") == {"type": "ephemeral"}
    assert "cache_control" not in out[2]


def test_single_element_list_caches_only_element() -> None:
    """單元素 — 整個 system 都 cache(退化行為)。"""
    out = _build_system_param(["only"])
    assert isinstance(out, list)
    assert len(out) == 1
    assert out[0] == {
        "type": "text",
        "text": "only",
        "cache_control": {"type": "ephemeral"},
    }


def test_empty_list_does_not_crash() -> None:
    """邊界:空 list 不應 crash(雖然 caller 不該傳)。"""
    out = _build_system_param([])
    assert out == []
