"""SkillTool — 讀 ~/.orion/skills/*.md,可由 ORION_SKILLS_DIR 覆蓋。"""

from __future__ import annotations

from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent
from orion_agent.tools.agent.skill_tool import SkillInput, SkillTool


@pytest.mark.asyncio
async def test_load_skill(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path))
    (tmp_path / "deploy.md").write_text("# Deploy\nrun ./deploy.sh\n")

    tool = SkillTool()
    events = [
        e
        async for e in tool.call(SkillInput(skill_name="deploy"), AgentContext())
    ]
    assert isinstance(events[0], TextEvent)
    assert "deploy.sh" in events[0].text


@pytest.mark.asyncio
async def test_list_when_empty_name(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path))
    (tmp_path / "a.md").write_text("a")
    (tmp_path / "b.md").write_text("b")

    tool = SkillTool()
    events = [
        e
        async for e in tool.call(SkillInput(skill_name=""), AgentContext())
    ]
    text = events[0].text  # type: ignore[union-attr]
    assert "- a" in text
    assert "- b" in text


@pytest.mark.asyncio
async def test_skill_not_found(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path))
    tool = SkillTool()
    events = [
        e
        async for e in tool.call(SkillInput(skill_name="absent"), AgentContext())
    ]
    assert isinstance(events[0], ErrorEvent)


@pytest.mark.asyncio
async def test_path_traversal_rejected(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("ORION_SKILLS_DIR", str(tmp_path))
    tool = SkillTool()
    events = [
        e
        async for e in tool.call(
            SkillInput(skill_name="../etc/passwd"), AgentContext()
        )
    ]
    assert isinstance(events[0], ErrorEvent)
    assert "invalid" in events[0].message.lower()


@pytest.mark.asyncio
async def test_no_dir_falls_back_to_builtin(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path,
) -> None:
    """Phase 8:user dir 不存在 → 仍可列出內建 skills(be-concise 等)。"""
    nope = tmp_path / "nonexistent"
    monkeypatch.setenv("ORION_SKILLS_DIR", str(nope))
    tool = SkillTool()
    events = [
        e
        async for e in tool.call(SkillInput(), AgentContext())
    ]
    assert isinstance(events[0], TextEvent)
    text = events[0].text.lower()
    assert "available skills" in text
    assert "be-concise" in text
