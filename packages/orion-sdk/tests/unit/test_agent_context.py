"""AgentContext 基礎行為。"""

from __future__ import annotations

from pathlib import Path

from orion_sdk.core.state import AgentContext, TokenBudget


def test_default_context_is_unique() -> None:
    a = AgentContext()
    b = AgentContext()
    assert a.session_id != b.session_id
    assert a.abort_event is not b.abort_event


def test_feature_flags_default_false() -> None:
    ctx = AgentContext()
    assert ctx.feature("anything") is False


def test_feature_flags_lookup() -> None:
    ctx = AgentContext(feature_flags={"x": True, "y": False})
    assert ctx.feature("x") is True
    assert ctx.feature("y") is False
    assert ctx.feature("z") is False


def test_cwd_override(tmp_path: Path) -> None:
    ctx = AgentContext(cwd=tmp_path)
    assert ctx.cwd == tmp_path


def test_token_budget_default() -> None:
    tb = TokenBudget()
    assert tb.max_input_tokens == 200_000
    assert tb.used_input_tokens == 0
