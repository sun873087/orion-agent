"""hooks.config_manager — settings.json hook 載入(shell + webhook)。"""

from __future__ import annotations

import pytest

from orion_sdk.hooks.config_manager import (
    load_hooks_from_settings,
    load_hooks_from_settings_for_web,
)
from orion_sdk.hooks.events import PreToolUseEvent, UserPromptSubmitEvent
from orion_sdk.hooks.registry import HookRegistry


def test_unknown_event_skipped() -> None:
    reg = HookRegistry()
    n = load_hooks_from_settings(
        {"hooks": {"NotAnEvent": [{"command": "echo"}]}}, reg,
    )
    assert n == 0


def test_loads_shell_hook() -> None:
    reg = HookRegistry()
    n = load_hooks_from_settings(
        {"hooks": {"PreToolUse": [{"command": "echo hi"}]}}, reg,
    )
    assert n == 1
    assert reg.count("PreToolUse") == 1


def test_loads_webhook_hook() -> None:
    reg = HookRegistry()
    n = load_hooks_from_settings(
        {"hooks": {"PostToolUse": [{"webhook": "https://x.example/hook"}]}}, reg,
    )
    assert n == 1


def test_web_only_rejects_shell() -> None:
    reg = HookRegistry()
    n = load_hooks_from_settings_for_web(
        {"hooks": {"PreToolUse": [{"command": "echo"}]}}, reg,
    )
    assert n == 0
    assert reg.count("PreToolUse") == 0


def test_web_only_accepts_webhook() -> None:
    reg = HookRegistry()
    n = load_hooks_from_settings_for_web(
        {"hooks": {"PreToolUse": [{"webhook": "https://x.example"}]}}, reg,
    )
    assert n == 1


@pytest.mark.asyncio
async def test_shell_hook_runs_and_returns_modified_input() -> None:
    """跑真的 shell;hook stdout 是 JSON → parse 成 PreToolUseResult。"""
    reg = HookRegistry()
    # /bin/cat 把 stdin echo 出來 — 那是 event JSON,不是合法 result;
    # 改用 printf 直接吐固定 JSON
    load_hooks_from_settings(
        {
            "hooks": {
                "PreToolUse": [
                    {"command": 'printf \'{"modified_input": {"x": 999}}\'',
                     "timeout_seconds": 3},
                ],
            },
        },
        reg,
    )
    res = await reg.fire_pre_tool_use(
        PreToolUseEvent(tool_name="Bash", tool_input={"x": 1}),
    )
    assert res.abort is False
    assert res.modified_input == {"x": 999}


@pytest.mark.asyncio
async def test_shell_hook_abort() -> None:
    reg = HookRegistry()
    load_hooks_from_settings(
        {
            "hooks": {
                "PreToolUse": [
                    {"command": 'printf \'{"abort": true, "abort_reason": "nope"}\'',
                     "timeout_seconds": 3},
                ],
            },
        },
        reg,
    )
    res = await reg.fire_pre_tool_use(
        PreToolUseEvent(tool_name="Bash", tool_input={}),
    )
    assert res.abort is True
    assert res.abort_reason == "nope"


@pytest.mark.asyncio
async def test_shell_hook_matcher_filter() -> None:
    """matcher.tool_name 不符 → handler 直接 return None,不跑 subprocess。"""
    reg = HookRegistry()
    load_hooks_from_settings(
        {
            "hooks": {
                "PreToolUse": [
                    {
                        "command": 'printf \'{"abort": true}\'',
                        "matcher": {"tool_name": "Edit"},
                    },
                ],
            },
        },
        reg,
    )
    # tool_name=Bash,不符 matcher,不會 abort
    res = await reg.fire_pre_tool_use(
        PreToolUseEvent(tool_name="Bash", tool_input={}),
    )
    assert res.abort is False


@pytest.mark.asyncio
async def test_shell_hook_user_prompt_additional_context() -> None:
    reg = HookRegistry()
    load_hooks_from_settings(
        {
            "hooks": {
                "UserPromptSubmit": [
                    {"command": 'printf \'{"additional_context": "extra context"}\'',
                     "timeout_seconds": 3},
                ],
            },
        },
        reg,
    )
    res = await reg.fire_user_prompt_submit(UserPromptSubmitEvent(prompt="hi"))
    assert res.abort is False
    assert res.additional_context == "extra context"
