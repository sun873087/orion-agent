"""GrepTool — 用 fallback 模式測,確保 ripgrep 缺席也能跑。"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.search.grep import GrepInput, GrepTool


@pytest.mark.asyncio
async def test_python_fallback_match(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello world\nTODO fix this\n")
    (tmp_path / "b.txt").write_text("TODO another\n")

    tool = GrepTool()
    with patch("orion_agent.tools.search.grep.shutil.which", return_value=None):
        events = [
            e
            async for e in tool.call(GrepInput(pattern="TODO"), tmp_ctx)
        ]
    assert isinstance(events[0], TextEvent)
    assert "TODO" in events[0].text


@pytest.mark.asyncio
async def test_python_fallback_no_match(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("hello\n")
    tool = GrepTool()
    with patch("orion_agent.tools.search.grep.shutil.which", return_value=None):
        events = [
            e
            async for e in tool.call(GrepInput(pattern="ZZZ_NOPE"), tmp_ctx)
        ]
    assert "no matches" in events[0].text.lower()  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_invalid_regex(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    (tmp_path / "a.txt").write_text("x")
    tool = GrepTool()
    with patch("orion_agent.tools.search.grep.shutil.which", return_value=None):
        events = [
            e
            async for e in tool.call(GrepInput(pattern="[invalid"), tmp_ctx)
        ]
    assert isinstance(events[0], ErrorEvent)
    assert "regex" in events[0].message.lower()


@pytest.mark.asyncio
async def test_relative_path_rejected(tmp_ctx: AgentContext) -> None:
    tool = GrepTool()
    events = [
        e
        async for e in tool.call(GrepInput(pattern="x", path="relative"), tmp_ctx)
    ]
    assert isinstance(events[0], ErrorEvent)
