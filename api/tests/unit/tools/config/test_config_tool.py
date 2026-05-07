"""ConfigTool — get / set / delete / list + dot-path。"""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest

from orion_agent.core.state import AgentContext
from orion_agent.core.tool import ErrorEvent, TextEvent, ToolEvent
from orion_agent.tools.config.config_tool import (
    ConfigInput,
    ConfigTool,
    _del_at,
    _get_at,
    _set_at,
    load_settings,
    save_settings,
    settings_path,
)


@pytest.fixture(autouse=True)
def _isolate_orion_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_HOME", str(tmp_path / ".orion"))


async def _collect(it: AsyncIterator[ToolEvent]) -> list[ToolEvent]:
    return [ev async for ev in it]


def test_dot_path_helpers() -> None:
    d: dict = {}
    _set_at(d, "a.b.c", 42)
    assert _get_at(d, "a.b.c") == 42
    assert _del_at(d, "a.b.c") is True
    assert _get_at(d, "a.b.c") is None


def test_settings_path_uses_orion_home() -> None:
    p = settings_path()
    assert ".orion" in str(p)
    assert p.name == "settings.json"


def test_save_load_roundtrip() -> None:
    save_settings({"foo": 1, "bar": {"baz": 2}})
    loaded = load_settings()
    assert loaded == {"foo": 1, "bar": {"baz": 2}}


def test_load_empty_when_no_file() -> None:
    assert load_settings() == {}


@pytest.mark.asyncio
async def test_get_action() -> None:
    save_settings({"hooks": {"PreToolUse": [{"command": "echo"}]}})
    tool = ConfigTool()
    events = await _collect(
        tool.call(ConfigInput(action="get", key="hooks.PreToolUse"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "PreToolUse" in text or "echo" in text


@pytest.mark.asyncio
async def test_set_action_writes_to_disk() -> None:
    tool = ConfigTool()
    await _collect(
        tool.call(
            ConfigInput(action="set", key="theme", value_json='"dark"'),
            AgentContext(),
        ),
    )
    assert load_settings()["theme"] == "dark"


@pytest.mark.asyncio
async def test_delete_action() -> None:
    save_settings({"foo": 1, "bar": 2})
    tool = ConfigTool()
    await _collect(
        tool.call(ConfigInput(action="delete", key="foo"), AgentContext()),
    )
    assert load_settings() == {"bar": 2}


@pytest.mark.asyncio
async def test_delete_missing_returns_error() -> None:
    save_settings({"foo": 1})
    tool = ConfigTool()
    events = await _collect(
        tool.call(ConfigInput(action="delete", key="nope"), AgentContext()),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)


@pytest.mark.asyncio
async def test_list_action() -> None:
    save_settings({"foo": 1, "bar": 2})
    tool = ConfigTool()
    events = await _collect(
        tool.call(ConfigInput(action="list"), AgentContext()),
    )
    text = next(e.text for e in events if isinstance(e, TextEvent))
    assert "foo" in text and "bar" in text


@pytest.mark.asyncio
async def test_set_invalid_json_returns_error() -> None:
    tool = ConfigTool()
    events = await _collect(
        tool.call(
            ConfigInput(action="set", key="x", value_json="{not valid"),
            AgentContext(),
        ),
    )
    assert any(isinstance(e, ErrorEvent) for e in events)
