"""GlobTool。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.core.tool import ErrorEvent, TextEvent
from orion_sdk.tools.search.glob import GlobInput, GlobTool


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


@pytest.mark.asyncio
async def test_truncates_at_max_results_and_keeps_newest(
    tmp_ctx: AgentContext, tmp_path: Path
) -> None:
    """建 600 個檔(>500 上限),確認 heap 只保留最新的 500 個 + truncated 註記。"""
    import os
    import time

    # 建 600 檔,mtime 遞增(最後建的最新)
    for i in range(600):
        p = tmp_path / f"f{i:04d}.txt"
        p.write_text(str(i))
        os.utime(p, (time.time() + i, time.time() + i))

    tool = GlobTool()
    events = [e async for e in tool.call(GlobInput(pattern="*.txt"), tmp_ctx)]
    assert isinstance(events[0], TextEvent)
    text = events[0].text
    # 應只回 500 match
    assert "500 match(es)" in text
    assert "more matches exist" in text
    # 最新的 f0599 應在(top of newest 500)
    assert "f0599.txt" in text
    # 最舊的 f0000 應不在(被替換掉)
    assert "f0000.txt" not in text


@pytest.mark.asyncio
async def test_handles_unreadable_file_gracefully(
    tmp_ctx: AgentContext, tmp_path: Path
) -> None:
    """有 stat() 失敗的檔(broken symlink)→ skip 不 crash。"""
    (tmp_path / "good.txt").write_text("ok")
    bad = tmp_path / "bad-symlink.txt"
    # 指向不存在的目標 → stat() 會 raise OSError
    bad.symlink_to(tmp_path / "does_not_exist")

    tool = GlobTool()
    events = [e async for e in tool.call(GlobInput(pattern="*.txt"), tmp_ctx)]
    assert isinstance(events[0], TextEvent)
    assert "good.txt" in events[0].text
