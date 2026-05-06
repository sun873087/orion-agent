"""FileEditTool。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.file.edit import FileEditInput, FileEditTool


@pytest.mark.asyncio
async def test_basic_replace(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("hello world\n", encoding="utf-8")
    tool = FileEditTool()
    events = [
        e
        async for e in tool.call(
            FileEditInput(path=str(p), old_string="world", new_string="orion"),
            tmp_ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert p.read_text() == "hello orion\n"


@pytest.mark.asyncio
async def test_old_string_not_found(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("hello\n", encoding="utf-8")
    tool = FileEditTool()
    events = [
        e
        async for e in tool.call(
            FileEditInput(path=str(p), old_string="absent", new_string="x"),
            tmp_ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "not found" in events[0].message.lower()


@pytest.mark.asyncio
async def test_ambiguous_match_without_replace_all(
    tmp_ctx: AgentContext, tmp_path: Path
) -> None:
    p = tmp_path / "f.txt"
    p.write_text("foo\nfoo\nfoo\n", encoding="utf-8")
    tool = FileEditTool()
    events = [
        e
        async for e in tool.call(
            FileEditInput(path=str(p), old_string="foo", new_string="bar"),
            tmp_ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "appears 3 times" in events[0].message


@pytest.mark.asyncio
async def test_replace_all(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("foo\nfoo\nfoo\n", encoding="utf-8")
    tool = FileEditTool()
    events = [
        e
        async for e in tool.call(
            FileEditInput(
                path=str(p), old_string="foo", new_string="bar", replace_all=True
            ),
            tmp_ctx,
        )
    ]
    assert isinstance(events[0], TextEvent)
    assert p.read_text() == "bar\nbar\nbar\n"


@pytest.mark.asyncio
async def test_identical_old_new_rejected(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "f.txt"
    p.write_text("x", encoding="utf-8")
    tool = FileEditTool()
    events = [
        e
        async for e in tool.call(
            FileEditInput(path=str(p), old_string="x", new_string="x"),
            tmp_ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_missing_file(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    p = tmp_path / "absent.txt"
    tool = FileEditTool()
    events = [
        e
        async for e in tool.call(
            FileEditInput(path=str(p), old_string="x", new_string="y"),
            tmp_ctx,
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "does not exist" in events[0].message.lower()
