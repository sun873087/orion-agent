"""memory/extract.py — 用 MockProvider 驗 fork extract 流程。"""

from __future__ import annotations

import pytest

from orion_model.types import NormalizedMessage
from orion_sdk.memory.extract import (
    extract_memories,
    parse_extract_output,
)
from orion_sdk.memory.paths import user_memory_paths
from orion_sdk.memory.types import Memory, MemoryFrontmatter, MemoryType
from orion_sdk._testing import MockProvider, MockTurn


def test_parse_extract_output_none() -> None:
    assert parse_extract_output("NONE") == []
    assert parse_extract_output("") == []


def test_parse_extract_output_single_block() -> None:
    text = """\
FILE: feedback_test.md
---
name: Test
description: test mem
type: feedback
---
Body line 1
Body line 2
END
"""
    blocks = parse_extract_output(text)
    assert len(blocks) == 1
    op, fname, content = blocks[0]
    assert op == "create"
    assert fname == "feedback_test.md"
    assert "Body line 1" in content
    assert content.startswith("---")


def test_parse_extract_output_multiple() -> None:
    text = """\
FILE: a.md
---
name: a
description: A
type: user
---
body a
END

FILE: b.md
---
name: b
description: B
type: feedback
---
body b
END
"""
    blocks = parse_extract_output(text)
    assert len(blocks) == 2
    assert blocks[0][:2] == ("create", "a.md")
    assert blocks[1][:2] == ("create", "b.md")


def test_parse_extract_output_update_block() -> None:
    """UPDATE 區塊解析,op == 'update'。"""
    text = """\
UPDATE: feedback_existing.md
---
name: Updated
description: updated desc
type: feedback
---
merged body
END
"""
    blocks = parse_extract_output(text)
    assert len(blocks) == 1
    op, fname, _ = blocks[0]
    assert op == "update"
    assert fname == "feedback_existing.md"


def test_parse_extract_output_mixed_create_and_update() -> None:
    """FILE + UPDATE 區塊可同時出現。"""
    text = """\
UPDATE: feedback_existing.md
---
name: Updated
description: u
type: feedback
---
merged
END

FILE: project_new.md
---
name: New
description: n
type: project
---
fresh
END
"""
    blocks = parse_extract_output(text)
    assert len(blocks) == 2
    assert blocks[0][0] == "update"
    assert blocks[0][1] == "feedback_existing.md"
    assert blocks[1][0] == "create"
    assert blocks[1][1] == "project_new.md"


@pytest.mark.asyncio
async def test_extract_writes_new_files(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()

    # MockProvider 回兩筆 FILE block
    mock_response = """\
FILE: feedback_test.md
---
name: Be brief
description: User asked for terse answers
type: feedback
---
Always keep responses short.
END
"""
    provider = MockProvider(turns=[MockTurn(text=mock_response)])
    msgs = [
        NormalizedMessage(role="user", content="please be terse"),
        NormalizedMessage(role="assistant", content="ok"),
    ]
    new = await extract_memories(
        msgs, [], provider=provider, paths=paths,  # type: ignore[arg-type]
    )
    assert len(new) == 1
    assert new[0].name == "Be brief"
    assert (paths.memory_dir / "feedback_test.md").exists()
    # MEMORY.md 也被寫
    assert paths.index.exists()
    assert "Be brief" in paths.index.read_text()


@pytest.mark.asyncio
async def test_extract_none_response(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    provider = MockProvider(turns=[MockTurn(text="NONE")])
    msgs = [NormalizedMessage(role="user", content="...")]
    new = await extract_memories(msgs, [], provider=provider, paths=paths)  # type: ignore[arg-type]
    assert new == []


@pytest.mark.asyncio
async def test_extract_skips_existing_file(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    existing_path = paths.memory_dir / "feedback_test.md"
    existing_path.write_text(
        "---\nname: Existing\ndescription: existing\ntype: feedback\n---\nold body"
    )
    existing = [Memory(
        frontmatter=MemoryFrontmatter(
            name="Existing", description="existing", type=MemoryType.FEEDBACK,
        ),
        body="old body", file_path=existing_path,
    )]

    mock_response = """\
FILE: feedback_test.md
---
name: New
description: new
type: feedback
---
new body
END
"""
    provider = MockProvider(turns=[MockTurn(text=mock_response)])
    msgs = [NormalizedMessage(role="user", content="...")]
    new = await extract_memories(
        msgs, existing, provider=provider, paths=paths,  # type: ignore[arg-type]
    )
    # 不該覆蓋
    assert len(new) == 0
    assert "old body" in existing_path.read_text()


@pytest.mark.asyncio
async def test_extract_invalid_filename_skipped(tmp_path) -> None:  # noqa: ANN001
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    mock_response = """\
FILE: ../etc/passwd
---
name: bad
description: bad
type: user
---
body
END
"""
    provider = MockProvider(turns=[MockTurn(text=mock_response)])
    new = await extract_memories(
        [NormalizedMessage(role="user", content="x")],
        [], provider=provider, paths=paths,  # type: ignore[arg-type]
    )
    assert new == []


# ─── UPDATE 操作(Layer 1 寫入端去重)──────────────────────────────────────


@pytest.mark.asyncio
async def test_extract_update_overwrites_existing_file(tmp_path) -> None:  # noqa: ANN001
    """UPDATE 對既有 memory 直接 overwrite,不受 overwrite=False 限制。"""
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()
    existing_path = paths.memory_dir / "feedback_test.md"
    existing_path.write_text(
        "---\nname: Old\ndescription: old\ntype: feedback\n---\nold body\n"
    )
    existing = [Memory(
        frontmatter=MemoryFrontmatter(
            name="Old", description="old", type=MemoryType.FEEDBACK,
        ),
        body="old body", file_path=existing_path,
    )]

    mock_response = """\
UPDATE: feedback_test.md
---
name: New
description: merged
type: feedback
---
new merged body
END
"""
    provider = MockProvider(turns=[MockTurn(text=mock_response)])
    new = await extract_memories(
        [NormalizedMessage(role="user", content="x")],
        existing, provider=provider, paths=paths,  # type: ignore[arg-type]
    )
    assert len(new) == 1
    assert new[0].name == "New"
    content = existing_path.read_text()
    assert "new merged body" in content
    assert "old body" not in content

    # MEMORY.md 應只有一筆(被取代,不是新增)
    index_text = paths.index.read_text()
    assert index_text.count("feedback_test.md") == 1


@pytest.mark.asyncio
async def test_extract_update_skips_nonexistent_file(tmp_path) -> None:  # noqa: ANN001
    """UPDATE 指向不存在的檔案 → LLM 在編造,skip。"""
    paths = user_memory_paths("bob", users_root=tmp_path)
    paths.ensure_dirs()

    mock_response = """\
UPDATE: feedback_hallucinated.md
---
name: Fake
description: f
type: feedback
---
body
END
"""
    provider = MockProvider(turns=[MockTurn(text=mock_response)])
    new = await extract_memories(
        [NormalizedMessage(role="user", content="x")],
        [], provider=provider, paths=paths,  # type: ignore[arg-type]
    )
    assert new == []
    assert not (paths.memory_dir / "feedback_hallucinated.md").exists()


def test_summarize_existing_memories_includes_body_preview() -> None:
    """既有 memory 摘要應含 filename 與 body preview,讓 LLM 能判斷是否該 UPDATE。"""
    from orion_sdk.memory.extract import _summarize_existing_memories

    mem = Memory(
        frontmatter=MemoryFrontmatter(
            name="Likes ramen", description="lunch preference",
            type=MemoryType.USER,
        ),
        body="User mentioned preference for tonkotsu ramen on rainy days.",
        file_path=user_memory_paths("bob").memory_file("user_food.md"),
    )
    summary = _summarize_existing_memories([mem])
    assert "user_food.md" in summary
    assert "Likes ramen" in summary
    assert "tonkotsu" in summary  # body preview 含進去


def test_summarize_existing_memories_truncates_long_body() -> None:
    """過長 body 應截掉並加 '...'。"""
    from orion_sdk.memory.extract import _BODY_PREVIEW_CHARS, _summarize_existing_memories

    long_body = "x" * (_BODY_PREVIEW_CHARS + 100)
    mem = Memory(
        frontmatter=MemoryFrontmatter(
            name="Long", description="d", type=MemoryType.USER,
        ),
        body=long_body,
        file_path=user_memory_paths("bob").memory_file("user_long.md"),
    )
    summary = _summarize_existing_memories([mem])
    assert "..." in summary
    # 前 200 字應出現,但不該整個 300 都出現
    assert "x" * _BODY_PREVIEW_CHARS in summary
    assert "x" * (_BODY_PREVIEW_CHARS + 50) not in summary
