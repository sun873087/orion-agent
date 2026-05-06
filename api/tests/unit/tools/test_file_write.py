"""FileWriteTool。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.file.write import FileWriteInput, FileWriteTool


@pytest.mark.asyncio
async def test_create_new_file(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "new.txt"
    tool = FileWriteTool()
    events = [
        e
        async for e in tool.call(
            FileWriteInput(path=str(p), content="hello world\n"), tmp_ctx
        )
    ]
    assert len(events) == 1
    assert isinstance(events[0], TextEvent)
    assert "created" in events[0].text
    assert p.read_text() == "hello world\n"


@pytest.mark.asyncio
async def test_overwrite_existing(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("old", encoding="utf-8")
    tool = FileWriteTool()
    events = [
        e
        async for e in tool.call(FileWriteInput(path=str(p), content="new"), tmp_ctx)
    ]
    assert isinstance(events[0], TextEvent)
    assert "overwrote" in events[0].text
    assert p.read_text() == "new"


@pytest.mark.asyncio
async def test_relative_path_rejected(tmp_ctx: AgentContext) -> None:
    tool = FileWriteTool()
    events = [
        e
        async for e in tool.call(
            FileWriteInput(path="relative.txt", content="x"), tmp_ctx
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "absolute" in events[0].message.lower()


@pytest.mark.asyncio
async def test_missing_parent_dir_rejected(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "nope" / "f.txt"
    tool = FileWriteTool()
    events = [
        e
        async for e in tool.call(FileWriteInput(path=str(p), content="x"), tmp_ctx)
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "parent" in events[0].message.lower()


def test_metadata_flags() -> None:
    tool = FileWriteTool()
    inp = FileWriteInput(path="/tmp/x", content="x")
    assert tool.is_concurrency_safe(inp) is False
    assert tool.is_read_only(inp) is False
