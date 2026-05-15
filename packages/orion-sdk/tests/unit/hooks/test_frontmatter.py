"""hooks.frontmatter — register_frontmatter_hooks(skill / plugin 內宣告 hook)。"""

from __future__ import annotations

from orion_sdk.hooks.frontmatter import register_frontmatter_hooks
from orion_sdk.hooks.registry import HookRegistry


def test_registers_event_handlers() -> None:
    reg = HookRegistry()
    n = register_frontmatter_hooks(
        [
            {"event": "PreToolUse", "command": "echo a"},
            {"event": "PostToolUse", "webhook": "https://x.example"},
        ],
        reg,
    )
    assert n == 2
    assert reg.count("PreToolUse") == 1
    assert reg.count("PostToolUse") == 1


def test_skips_unknown_event() -> None:
    reg = HookRegistry()
    n = register_frontmatter_hooks(
        [{"event": "WhateverEvent", "command": "echo"}], reg,
    )
    assert n == 0


def test_web_only_rejects_shell() -> None:
    reg = HookRegistry()
    n = register_frontmatter_hooks(
        [{"event": "PreToolUse", "command": "echo"}], reg, web_only=True,
    )
    assert n == 0


def test_handles_non_list() -> None:
    reg = HookRegistry()
    assert register_frontmatter_hooks("not a list", reg) == 0  # type: ignore[arg-type]
