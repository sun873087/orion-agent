"""/help / /model 內建命令。"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from orion_agent.commands.builtin.help import HelpCommand
from orion_agent.commands.builtin.model import ModelCommand
from orion_agent.commands.registry import (
    clear_registry,
    register_builtins,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    clear_registry()


@dataclass
class _MockProvider:
    name: str = "anthropic"
    model: str = "claude-sonnet-4-6"


@dataclass
class _MockConv:
    provider: _MockProvider | None = None


@pytest.mark.asyncio
async def test_help_lists_registered() -> None:
    register_builtins()
    cmd = HelpCommand()
    res = await cmd.execute("", None, None)
    assert res.text is not None
    assert "/help" in res.text
    assert "/model" in res.text


@pytest.mark.asyncio
async def test_help_when_empty() -> None:
    cmd = HelpCommand()
    res = await cmd.execute("", None, None)
    assert res.text is not None
    assert "no commands" in res.text


@pytest.mark.asyncio
async def test_model_show_current() -> None:
    cmd = ModelCommand()
    conv = _MockConv(provider=_MockProvider(model="claude-haiku-4-5"))
    res = await cmd.execute("", None, conv)
    assert res.text is not None
    assert "claude-haiku-4-5" in res.text


@pytest.mark.asyncio
async def test_model_list() -> None:
    cmd = ModelCommand()
    conv = _MockConv(provider=_MockProvider(model="claude-sonnet-4-6"))
    res = await cmd.execute("list", None, conv)
    assert res.text is not None
    assert "claude-sonnet-4-6" in res.text
    assert "claude-opus-4-7" in res.text


@pytest.mark.asyncio
async def test_model_switch() -> None:
    cmd = ModelCommand()
    provider = _MockProvider(model="claude-sonnet-4-6")
    conv = _MockConv(provider=provider)
    res = await cmd.execute("claude-haiku-4-5", None, conv)
    assert provider.model == "claude-haiku-4-5"
    assert res.text is not None
    assert "→" in res.text or "haiku" in res.text


@pytest.mark.asyncio
async def test_model_no_provider() -> None:
    cmd = ModelCommand()
    conv = _MockConv(provider=None)
    res = await cmd.execute("", None, conv)
    assert res.text is not None
    assert "no provider" in res.text
