"""api/event_schema.py — Pydantic discriminated unions。"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orion_agent.api.event_schema import (
    AbortEvent,
    AssistantTextEvent,
    PermissionAskEvent,
    PermissionDecisionEvent,
    TerminalEvent,
    UserMessageEvent,
    parse_client_event,
    serialize_server_event,
)


def test_parse_user_message() -> None:
    ev = parse_client_event({"type": "user_message", "content": "hi"})
    assert isinstance(ev, UserMessageEvent)
    assert ev.content == "hi"


def test_parse_permission_decision() -> None:
    ev = parse_client_event({
        "type": "permission_decision",
        "request_id": "abc",
        "decision": "allow",
    })
    assert isinstance(ev, PermissionDecisionEvent)


def test_parse_invalid_decision_raises() -> None:
    with pytest.raises(ValidationError):
        parse_client_event({
            "type": "permission_decision",
            "request_id": "x",
            "decision": "maybe",
        })


def test_parse_abort() -> None:
    ev = parse_client_event({"type": "abort"})
    assert isinstance(ev, AbortEvent)


def test_parse_unknown_type_raises() -> None:
    with pytest.raises(ValueError, match="Unknown client event type"):
        parse_client_event({"type": "garbage"})


def test_serialize_server_event() -> None:
    ev = AssistantTextEvent(text="hello")
    out = serialize_server_event(ev)
    assert out == {"type": "assistant_text", "text": "hello"}


def test_permission_ask_default_timeout() -> None:
    ev = PermissionAskEvent(
        request_id="r1", tool_name="Bash", input={"command": "ls"},
    )
    assert ev.timeout_seconds == 60


def test_terminal_event() -> None:
    out = serialize_server_event(
        TerminalEvent(reason="natural_stop", total_turns=3),
    )
    assert out["type"] == "terminal"
    assert out["total_turns"] == 3
