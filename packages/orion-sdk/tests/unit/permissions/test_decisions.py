"""permissions/decisions.py。"""

from __future__ import annotations

import pytest

from orion_sdk.core.state import AgentContext
from orion_sdk.permissions.decisions import (
    PermissionDecision,
    PermissionResult,
    always_allow,
    always_deny,
)


def test_decision_enum_values() -> None:
    assert PermissionDecision.ALLOW.value == "allow"
    assert PermissionDecision.ASK.value == "ask"
    assert PermissionDecision.DENY.value == "deny"


def test_permission_result_default_reason() -> None:
    r = PermissionResult(decision=PermissionDecision.ALLOW)
    assert r.reason == ""


@pytest.mark.asyncio
async def test_always_allow() -> None:
    r = await always_allow(None, {}, AgentContext())  # type: ignore[arg-type]
    assert r.decision == PermissionDecision.ALLOW


@pytest.mark.asyncio
async def test_always_deny() -> None:
    r = await always_deny(None, {}, AgentContext())  # type: ignore[arg-type]
    assert r.decision == PermissionDecision.DENY
    assert r.reason
