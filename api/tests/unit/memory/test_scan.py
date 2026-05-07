"""memory/scan.py — frontmatter parser + dir scan。"""

from __future__ import annotations

from orion_agent.memory.paths import user_memory_paths
from orion_agent.memory.scan import (
    parse_frontmatter,
    render_index,
    scan_memory_dir,
    write_index,
)
from orion_agent.memory.types import Memory, MemoryFrontmatter, MemoryType


def test_parse_frontmatter_basic() -> None:
    text = (
        "---\n"
        "name: My memory\n"
        "description: A test memory\n"
        "type: user\n"
        "---\n"
        "Body text here."
    )
    fm, body = parse_frontmatter(text)
    assert fm is not None
    assert fm.name == "My memory"
    assert fm.description == "A test memory"
    assert fm.type == MemoryType.USER
    assert body.strip() == "Body text here."


def test_parse_frontmatter_no_type() -> None:
    text = "---\nname: x\ndescription: y\n---\n"
    fm, _ = parse_frontmatter(text)
    assert fm is not None
    assert fm.type is None


def test_parse_frontmatter_invalid_type_returns_none_type() -> None:
    text = "---\nname: x\ndescription: y\ntype: weirdo\n---\n"
    fm, _ = parse_frontmatter(text)
    assert fm is not None
    assert fm.type is None


def test_parse_frontmatter_missing_required_returns_none() -> None:
    text = "---\nname: x\n---\nbody"  # 缺 description
    fm, body = parse_frontmatter(text)
    assert fm is None
    assert body == text  # 整段回


def test_parse_frontmatter_no_delimiters() -> None:
    text = "Just plain markdown without frontmatter"
    fm, body = parse_frontmatter(text)
    assert fm is None
    assert body == text


def test_scan_memory_dir_skips_invalid(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    # valid
    (paths.memory_dir / "user_alice.md").write_text(
        "---\nname: Alice\ndescription: She is alice\ntype: user\n---\nbody"
    )
    # invalid frontmatter
    (paths.memory_dir / "broken.md").write_text("no frontmatter here")
    # MEMORY.md should be skipped
    (paths.memory_dir / "MEMORY.md").write_text("# index")
    # hidden
    (paths.memory_dir / ".hidden.md").write_text(
        "---\nname: hidden\ndescription: x\n---\n"
    )

    index = scan_memory_dir(paths)
    assert len(index.memories) == 1
    assert index.memories[0].name == "Alice"


def test_scan_memory_dir_empty(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    index = scan_memory_dir(paths)
    assert len(index.memories) == 0


def test_scan_by_type(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    for i, t in enumerate(["user", "feedback", "user", "project"]):
        (paths.memory_dir / f"{t}_m{i}.md").write_text(
            f"---\nname: m{i}\ndescription: x\ntype: {t}\n---\nbody"
        )
    index = scan_memory_dir(paths)
    assert len(index.by_type(MemoryType.USER)) == 2
    assert len(index.by_type(MemoryType.FEEDBACK)) == 1
    assert len(index.by_type(MemoryType.PROJECT)) == 1


def test_render_index(tmp_path) -> None:  # noqa: ANN001
    memories = [
        Memory(
            frontmatter=MemoryFrontmatter(
                name="Alice profile", description="user info", type=MemoryType.USER,
            ),
            body="...", file_path=tmp_path / "user_alice.md",
        ),
        Memory(
            frontmatter=MemoryFrontmatter(
                name="No tabs rule", description="dont use tabs", type=MemoryType.FEEDBACK,
            ),
            body="...", file_path=tmp_path / "feedback_tabs.md",
        ),
    ]
    text = render_index(memories)
    assert "## User" in text
    assert "## Feedback" in text
    assert "[Alice profile]" in text
    assert "user info" in text


def test_write_index(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    memories = [
        Memory(
            frontmatter=MemoryFrontmatter(
                name="x", description="y", type=MemoryType.USER,
            ),
            body="z", file_path=paths.memory_dir / "user_x.md",
        ),
    ]
    write_index(paths, memories)
    assert paths.index.exists()
    assert "user_x.md" in paths.index.read_text(encoding="utf-8")
