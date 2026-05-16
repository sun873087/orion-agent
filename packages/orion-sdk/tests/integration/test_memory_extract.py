"""Real-API integration:LLM-based memory extraction。

驗證真 LLM 能從對話判讀出值得記的 user fact / preference,並產出合法
markdown memory file with frontmatter。
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from orion_model.provider import get_provider
from orion_model.types import NormalizedMessage, TextBlock
from orion_sdk.memory.extract import extract_memories
from orion_sdk.memory.paths import MemoryPaths

pytestmark = pytest.mark.skipif(
    not os.environ.get("ANTHROPIC_API_KEY"),
    reason="ANTHROPIC_API_KEY not set",
)


@pytest.mark.asyncio
async def test_extract_user_fact_from_conversation(tmp_path: Path) -> None:
    """User 在對話中宣告自己是資深 Go 開發,extract 應產一個 user-type memory。"""
    paths = MemoryPaths(user_id="test-extract", root=tmp_path / "user-root")

    convo = [
        NormalizedMessage(
            role="user",
            content="I've been writing Go for ten years, mainly distributed systems work.",
        ),
        NormalizedMessage(
            role="assistant",
            content=[TextBlock(text="Got it — I'll keep that in mind for technical depth.")],
        ),
        NormalizedMessage(
            role="user",
            content="Please remember that fact for future sessions.",
        ),
    ]

    provider = get_provider("anthropic", "claude-haiku-4-5")
    written = await extract_memories(
        convo,
        existing_memories=[],
        provider=provider,
        paths=paths,
    )

    # 應該至少寫一個 memory 出來
    assert written, "LLM extracted no memories from clear user fact"

    # memory 內容應該提到 Go / experience
    found_go_memory = False
    for m in written:
        combined = (m.description + " " + m.body).lower()
        if "go" in combined and ("year" in combined or "experience" in combined or "distributed" in combined):
            found_go_memory = True
            # frontmatter 該有 type
            assert m.type is not None, f"memory {m.filename} missing type"
            break

    assert found_go_memory, f"no memory captured the Go fact. Got: {[m.filename for m in written]}"

    # 真實寫入 disk
    for m in written:
        target = paths.memory_dir / m.filename
        assert target.exists(), f"{m.filename} not written to disk"
