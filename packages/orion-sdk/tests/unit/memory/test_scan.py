"""memory/scan.py — frontmatter parser + dir scan。"""

from __future__ import annotations

from datetime import date

from orion_sdk.memory.paths import user_memory_paths
from orion_sdk.memory.scan import (
    parse_frontmatter,
    render_index,
    scan_memory_dir,
    write_index,
)
from orion_sdk.memory.types import Memory, MemoryFrontmatter, MemoryType


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


# ─── Layer 2: TTL / expires_at ─────────────────────────────────────────────


def test_parse_frontmatter_with_expires_at() -> None:
    text = (
        "---\n"
        "name: Q3 deadline\n"
        "description: ship Q3\n"
        "type: project\n"
        "expires_at: 2026-09-30\n"
        "---\n"
        "body"
    )
    fm, _ = parse_frontmatter(text)
    assert fm is not None
    assert fm.expires_at == date(2026, 9, 30)


def test_parse_frontmatter_without_expires_at_defaults_none() -> None:
    text = "---\nname: x\ndescription: y\ntype: user\n---\nbody"
    fm, _ = parse_frontmatter(text)
    assert fm is not None
    assert fm.expires_at is None


def test_parse_frontmatter_invalid_expires_at_treated_as_none() -> None:
    """壞日期格式不該卡死整個 parse,只是 expires_at = None。"""
    text = (
        "---\nname: x\ndescription: y\ntype: user\n"
        "expires_at: not-a-date\n---\nbody"
    )
    fm, _ = parse_frontmatter(text)
    assert fm is not None
    assert fm.expires_at is None


def test_scan_default_includes_expired(tmp_path) -> None:  # noqa: ANN001
    """預設(exclude_expired=False)應回全部 — 給 UI / extract 用。"""
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    (paths.memory_dir / "project_old.md").write_text(
        "---\nname: Old\ndescription: o\ntype: project\n"
        "expires_at: 2020-01-01\n---\nold body"
    )
    (paths.memory_dir / "user_durable.md").write_text(
        "---\nname: Durable\ndescription: d\ntype: user\n---\ndurable"
    )
    index = scan_memory_dir(paths)
    assert {m.name for m in index.memories} == {"Old", "Durable"}


def test_scan_exclude_expired_filters_past(tmp_path) -> None:  # noqa: ANN001
    """exclude_expired=True 應跳過 expires_at < today 的 memory。"""
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    (paths.memory_dir / "project_past.md").write_text(
        "---\nname: Past\ndescription: x\ntype: project\n"
        "expires_at: 2020-01-01\n---\nbody"
    )
    (paths.memory_dir / "project_future.md").write_text(
        "---\nname: Future\ndescription: x\ntype: project\n"
        "expires_at: 2099-12-31\n---\nbody"
    )
    (paths.memory_dir / "user_durable.md").write_text(
        "---\nname: Durable\ndescription: x\ntype: user\n---\nbody"
    )
    index = scan_memory_dir(
        paths, exclude_expired=True, today=date(2026, 5, 11),
    )
    names = {m.name for m in index.memories}
    assert names == {"Future", "Durable"}
    assert "Past" not in names


def test_scan_exclude_expired_boundary_today(tmp_path) -> None:  # noqa: ANN001
    """expires_at == today 視為仍有效(隔天才過期)。"""
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    (paths.memory_dir / "project_today.md").write_text(
        "---\nname: Today\ndescription: x\ntype: project\n"
        "expires_at: 2026-05-11\n---\nbody"
    )
    index = scan_memory_dir(
        paths, exclude_expired=True, today=date(2026, 5, 11),
    )
    assert [m.name for m in index.memories] == ["Today"]


def test_scan_exclude_expired_no_expiry_never_filtered(tmp_path) -> None:  # noqa: ANN001
    """沒設 expires_at 的 memory 永遠保留。"""
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    (paths.memory_dir / "user_a.md").write_text(
        "---\nname: A\ndescription: x\ntype: user\n---\nbody"
    )
    index = scan_memory_dir(
        paths, exclude_expired=True, today=date(2099, 1, 1),
    )
    assert [m.name for m in index.memories] == ["A"]
