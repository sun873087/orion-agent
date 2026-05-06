"""transitions.py 基礎型別。"""

from __future__ import annotations

from orion_agent.core.transitions import Continue, Terminal


def test_terminal_default_reason() -> None:
    t = Terminal()
    assert t.reason == "natural_stop"


def test_terminal_custom_reason() -> None:
    t = Terminal(reason="max_turns_reached")
    assert t.reason == "max_turns_reached"


def test_continue_requires_reason() -> None:
    c = Continue(reason="tool_results")
    assert c.reason == "tool_results"


def test_terminal_continue_distinct() -> None:
    """型別系統能用 isinstance 區分。"""
    items = [Continue(reason="x"), Terminal(), Continue(reason="y")]
    terminals = [i for i in items if isinstance(i, Terminal)]
    continues = [i for i in items if isinstance(i, Continue)]
    assert len(terminals) == 1
    assert len(continues) == 2
