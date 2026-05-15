"""prompt/boundary.py — split_at_boundary 三條路徑。"""

from __future__ import annotations

from orion_sdk.prompt.boundary import (
    SYSTEM_PROMPT_DYNAMIC_BOUNDARY,
    split_at_boundary,
)


def test_no_boundary_returns_all_static() -> None:
    static, dynamic = split_at_boundary("just static text")
    assert static == "just static text"
    assert dynamic == ""


def test_with_boundary_splits() -> None:
    text = f"static\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\ndynamic"
    static, dynamic = split_at_boundary(text)
    assert static == "static"
    assert dynamic == "dynamic"


def test_boundary_at_start() -> None:
    text = f"{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}\ndynamic only"
    static, dynamic = split_at_boundary(text)
    assert static == ""
    assert dynamic == "dynamic only"


def test_boundary_at_end() -> None:
    text = f"static only\n{SYSTEM_PROMPT_DYNAMIC_BOUNDARY}"
    static, dynamic = split_at_boundary(text)
    assert static == "static only"
    assert dynamic == ""
