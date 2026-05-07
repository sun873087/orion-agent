"""memory/extract.py — 用 MockProvider 驗 fork extract 流程。"""

from __future__ import annotations

import pytest

from orion_agent.llm.types import NormalizedMessage
from orion_agent.memory.extract import (
    extract_memories,
    parse_extract_output,
)
from orion_agent.memory.paths import user_memory_paths
from orion_agent.memory.types import Memory, MemoryFrontmatter, MemoryType
from tests.conftest import MockProvider, MockTurn


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
    fname, content = blocks[0]
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
    assert blocks[0][0] == "a.md"
    assert blocks[1][0] == "b.md"


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
