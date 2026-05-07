"""memory/render.py。"""

from __future__ import annotations

from pathlib import Path

from orion_agent.memory.render import (
    prepend_to_system_prompt,
    render_memories,
)
from orion_agent.memory.types import Memory, MemoryFrontmatter, MemoryType


def _mk(name: str, description: str, body: str, t: MemoryType | None = MemoryType.USER) -> Memory:
    return Memory(
        frontmatter=MemoryFrontmatter(name=name, description=description, type=t),
        body=body,
        file_path=Path(f"/tmp/{name}.md"),
    )


def test_render_empty_returns_empty() -> None:
    assert render_memories([]) == ""


def test_render_single_memory_includes_name_desc_body() -> None:
    m = _mk("Alice profile", "She is alice", "She prefers Python.")
    text = render_memories([m])
    assert "Alice profile" in text
    assert "She is alice" in text
    assert "She prefers Python." in text
    assert "[user]" in text  # type tag


def test_render_no_type_omits_tag() -> None:
    m = _mk("X", "y", "body", t=None)
    text = render_memories([m])
    assert "X" in text
    assert "[None]" not in text
    assert "[user]" not in text


def test_prepend_to_system_prompt_adds_block() -> None:
    base = "you are a helpful assistant"
    m = _mk("Alice", "user info", "She likes Python")
    out = prepend_to_system_prompt(base, [m])
    assert out.endswith(base)
    assert "<memories>" in out
    assert out.index("<memories>") < out.index(base)


def test_prepend_with_no_memories_returns_base() -> None:
    base = "x"
    assert prepend_to_system_prompt(base, []) == base
