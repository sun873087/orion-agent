"""GlobTool。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.search.glob import GlobInput, GlobTool


@pytest.mark.asyncio
async def test_glob_simple_pattern(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.py").write_text("b")
    (tmp_path / "c.txt").write_text("c")

    tool = GlobTool()
    events = [
        e async for e in tool.call(GlobInput(pattern="*.py"), tmp_ctx)
    ]
    assert isinstance(events[0], TextEvent)
    text = events[0].text
    assert "a.py" in text
    assert "b.py" in text
    assert "c.txt" not in text


@pytest.mark.asyncio
async def test_glob_recursive(tmp_ctx: AgentContext, tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "deep.py").write_text("x")
    (tmp_path / "top.py").write_text("y")

    tool = GlobTool()
    events = [
        e async for e in tool.call(GlobInput(pattern="**/*.py"), tmp_ctx)
    ]
    text = events[0].text  # type: ignore[union-attr]
    assert "deep.py" in text
    assert "top.py" in text


@pytest.mark.asyncio
async def test_no_matches(tmp_ctx: AgentContext) -> None:
    tool = GlobTool()
    events = [
        e async for e in tool.call(GlobInput(pattern="*.does_not_exist"), tmp_ctx)
    ]
    assert isinstance(events[0], TextEvent)
    assert "no files matched" in events[0].text.lower()


@pytest.mark.asyncio
async def test_relative_base_path_rejected(tmp_ctx: AgentContext) -> None:
    tool = GlobTool()
    events = [
        e
        async for e in tool.call(
            GlobInput(pattern="*", base_path="relative"), tmp_ctx
        )
    ]
    assert isinstance(events[0], ErrorEvent)
