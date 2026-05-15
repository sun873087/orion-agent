"""Slash command registry — register / get / list / register_builtins。"""

from __future__ import annotations

from typing import Any

import pytest

from orion_cli.commands.registry import (
    clear_registry,
    get_command,
    list_commands,
    register_builtins,
    register_command,
)
from orion_cli.commands.types import Command, CommandResult


@pytest.fixture(autouse=True)
def _clean() -> None:
    clear_registry()


class _Dummy:
    name = "dummy"
    description = "test command"

    async def execute(
        self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
    ) -> CommandResult:
        return CommandResult(text=f"got: {args}")


def test_register_and_get() -> None:
    cmd = _Dummy()
    register_command(cmd)
    assert get_command("dummy") is cmd
    assert get_command("nope") is None


def test_register_duplicate_rejected() -> None:
    register_command(_Dummy())
    with pytest.raises(ValueError, match="already registered"):
        register_command(_Dummy())


def test_register_empty_name_rejected() -> None:
    class _Bad:
        name = ""
        description = "x"

        async def execute(
            self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
        ) -> CommandResult:
            return CommandResult()

    with pytest.raises(ValueError, match="non-empty"):
        register_command(_Bad())


def test_list_commands_sorted() -> None:
    class _A:
        name = "alpha"
        description = "a"

        async def execute(
            self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
        ) -> CommandResult:
            return CommandResult()

    class _B:
        name = "beta"
        description = "b"

        async def execute(
            self, args: str, ctx: Any, conversation: Any,  # noqa: ARG002
        ) -> CommandResult:
            return CommandResult()

    register_command(_B())
    register_command(_A())
    names = [c.name for c in list_commands()]
    assert names == ["alpha", "beta"]


def test_register_builtins_is_idempotent() -> None:
    register_builtins()
    register_builtins()  # 不該炸
    names = {c.name for c in list_commands()}
    assert "help" in names
    assert "model" in names


def test_command_protocol_runtime_check() -> None:
    cmd = _Dummy()
    assert isinstance(cmd, Command)
