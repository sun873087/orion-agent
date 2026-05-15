"""prompt/static_sections.py — 7 段內容存在 + 順序固定。"""

from __future__ import annotations

from orion_sdk.prompt.static_sections import (
    STATIC_SECTIONS_ORDER,
    render_static_block,
)


def test_seven_sections_exist() -> None:
    assert len(STATIC_SECTIONS_ORDER) == 7


def test_section_names_in_spec_order() -> None:
    expected = [
        "intro",
        "system_behavior",
        "doing_tasks",
        "actions",
        "tools",
        "tone_style",
        "output_efficiency",
    ]
    actual = [name for name, _ in STATIC_SECTIONS_ORDER]
    assert actual == expected


def test_render_static_block_contains_all_sections() -> None:
    text = render_static_block()
    for _, section_text in STATIC_SECTIONS_ORDER:
        # 取每段第一個 unique keyword 確認被包含
        first_line = section_text.splitlines()[0]
        assert first_line in text


def test_render_is_deterministic() -> None:
    """同 input 永遠同 output(prompt cache 穩定的關鍵)。"""
    a = render_static_block()
    b = render_static_block()
    assert a == b
