"""FileReadTool 行為。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.tools.file.read import FileReadInput, FileReadTool


@pytest.mark.asyncio
async def test_read_file_with_line_numbers(
    tmp_ctx: AgentContext, sample_text_file: Path
) -> None:
    tool = FileReadTool()
    events = [
        e
        async for e in tool.call(
            FileReadInput(path=str(sample_text_file)), tmp_ctx
        )
    ]
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    text = events[0].text
    assert "1\talpha" in text
    assert "5\tepsilon" in text


@pytest.mark.asyncio
async def test_read_offset_and_limit(
    tmp_ctx: AgentContext, sample_text_file: Path
) -> None:
    tool = FileReadTool()
    events = [
        e
        async for e in tool.call(
            FileReadInput(path=str(sample_text_file), offset=2, limit=2), tmp_ctx
        )
    ]
    text = events[0].text  # type: ignore[union-attr]
    assert "3\tgamma" in text
    assert "4\tdelta" in text
    assert "5\tepsilon" not in text  # limit=2 切掉
    assert "1\talpha" not in text  # offset=2 跳過


@pytest.mark.asyncio
async def test_relative_path_rejected(tmp_ctx: AgentContext) -> None:
    tool = FileReadTool()
    events = [e async for e in tool.call(FileReadInput(path="relative.txt"), tmp_ctx)]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "absolute" in events[0].message.lower()


@pytest.mark.asyncio
async def test_missing_file_returns_error(
    tmp_ctx: AgentContext, tmp_path: Path
) -> None:
    tool = FileReadTool()
    nonexistent = tmp_path / "nope.txt"
    events = [
        e async for e in tool.call(FileReadInput(path=str(nonexistent)), tmp_ctx)
    ]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "not found" in events[0].message.lower()


@pytest.mark.asyncio
async def test_directory_rejected(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    tool = FileReadTool()
    events = [e async for e in tool.call(FileReadInput(path=str(tmp_path)), tmp_ctx)]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_oversized_file_rejected(
    tmp_ctx: AgentContext, tmp_path: Path
) -> None:
    big = tmp_path / "big.txt"
    big.write_bytes(b"x" * (300 * 1024))  # 300 KB > 256 KB 上限
    tool = FileReadTool()
    events = [e async for e in tool.call(FileReadInput(path=str(big)), tmp_ctx)]
    assert len(events) == 1
    assert isinstance(events[0], ErrorEvent)
    assert "too large" in events[0].message.lower()


def test_metadata_flags() -> None:
    tool = FileReadTool()
    inp = FileReadInput(path="/tmp/x")
    assert tool.is_read_only(inp) is True
    assert tool.is_concurrency_safe(inp) is True
    assert tool.name == "Read"
