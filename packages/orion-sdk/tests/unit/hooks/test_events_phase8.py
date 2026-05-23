"""hook events — to_serializable + 全 8 種 type label。"""

from __future__ import annotations

from orion_sdk.hooks.events import (
    HOOK_EVENT_NAMES,
    FileChangedEvent,
    PostToolUseFailureEvent,
    PreToolUseEvent,
    PreToolUseResult,
    SessionStartEvent,
    SetupEvent,
    SubagentStartEvent,
    UserPromptSubmitEvent,
    UserPromptSubmitResult,
)


def test_8_event_names() -> None:
    assert set(HOOK_EVENT_NAMES) == {
        "PreToolUse",
        "PostToolUse",
        "PostToolUseFailure",
        "UserPromptSubmit",
        "SessionStart",
        "Setup",
        "SubagentStart",
        "SubagentStop",
        "FileChanged",
    }


def test_pretooluse_to_serializable_omits_objects() -> None:
    ev = PreToolUseEvent(
        tool=None,
        tool_input={"x": 1},
        ctx=None,
        session_id="s1",
        user_id="u1",
        tool_name="Bash",
        tool_use_id="tu1",
    )
    s = ev.to_serializable()
    assert s["type"] == "PreToolUse"
    assert s["session_id"] == "s1"
    assert s["tool_name"] == "Bash"
    assert s["tool_input"] == {"x": 1}
    # 沒有 tool / ctx 在 serializable
    assert "tool" not in s
    assert "ctx" not in s


def test_user_prompt_submit_serializable() -> None:
    ev = UserPromptSubmitEvent(prompt="hi", session_id="s", user_id="u")
    s = ev.to_serializable()
    assert s == {
        "type": "UserPromptSubmit",
        "session_id": "s",
        "user_id": "u",
        "prompt": "hi",
    }


def test_session_start_serializable() -> None:
    ev = SessionStartEvent(cwd="/x", resumed=True, session_id="s", user_id="u")
    s = ev.to_serializable()
    assert s["type"] == "SessionStart"
    assert s["resumed"] is True
    assert s["cwd"] == "/x"


def test_subagent_start_serializable() -> None:
    ev = SubagentStartEvent(
        parent_session_id="P", subagent_type="Agent", prompt="task", session_id="s",
    )
    assert ev.to_serializable()["parent_session_id"] == "P"


def test_file_changed_serializable() -> None:
    ev = FileChangedEvent(file_path="/x.txt", change_type="modified")
    assert ev.to_serializable()["change_type"] == "modified"


def test_setup_serializable() -> None:
    assert SetupEvent().to_serializable()["type"] == "Setup"


def test_post_tool_use_failure_serializable() -> None:
    ev = PostToolUseFailureEvent(
        tool=None,
        tool_input={"x": 1},
        error_message="boom",
        session_id="s",
        tool_name="Bash",
        tool_use_id="tu1",
    )
    s = ev.to_serializable()
    assert s["type"] == "PostToolUseFailure"
    assert s["error_message"] == "boom"


def test_result_dataclasses() -> None:
    r = PreToolUseResult(abort=True, abort_reason="reason")
    assert r.abort is True
    assert r.modified_input is None

    u = UserPromptSubmitResult(additional_context="extra")
    assert u.abort is False
    assert u.additional_context == "extra"
