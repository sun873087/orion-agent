"""Permission rule persistence。Phase 13。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_agent.permissions.persistence import (
    PermissionRule,
    add_permission_rule,
    find_matching_rule,
    list_permission_rules,
    persist_decision_if_always,
    remove_permission_rule,
)


def test_add_rule_writes_to_file(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    rule = PermissionRule(tool_name="Bash", decision="allow")
    added = add_permission_rule(rule, settings_file=f)
    assert added is True
    saved = json.loads(f.read_text())
    assert saved["permissions"]["rules"] == [
        {"tool_name": "Bash", "decision": "allow"},
    ]


def test_add_rule_dedup(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    rule = PermissionRule(tool_name="Bash", decision="allow")
    assert add_permission_rule(rule, settings_file=f) is True
    assert add_permission_rule(rule, settings_file=f) is False
    saved = json.loads(f.read_text())
    assert len(saved["permissions"]["rules"]) == 1


def test_add_rule_distinguishes_decision(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    add_permission_rule(
        PermissionRule(tool_name="Bash", decision="allow"), settings_file=f,
    )
    add_permission_rule(
        PermissionRule(tool_name="Bash", decision="deny"), settings_file=f,
    )
    rules = list_permission_rules(settings_file=f)
    assert len(rules) == 2


def test_remove_rule(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    add_permission_rule(
        PermissionRule(tool_name="Bash", decision="allow"), settings_file=f,
    )
    add_permission_rule(
        PermissionRule(tool_name="Edit", decision="allow"), settings_file=f,
    )
    n = remove_permission_rule("Bash", settings_file=f)
    assert n == 1
    assert [r.tool_name for r in list_permission_rules(settings_file=f)] == ["Edit"]


def test_remove_rule_decision_filter(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    add_permission_rule(
        PermissionRule(tool_name="Bash", decision="allow"), settings_file=f,
    )
    add_permission_rule(
        PermissionRule(tool_name="Bash", decision="deny"), settings_file=f,
    )
    n = remove_permission_rule("Bash", decision="allow", settings_file=f)
    assert n == 1
    rules = list_permission_rules(settings_file=f)
    assert [r.decision for r in rules] == ["deny"]


def test_remove_nonexistent_returns_zero(tmp_path: Path) -> None:
    f = tmp_path / "settings.json"
    assert remove_permission_rule("Nope", settings_file=f) == 0


def test_persist_decision_if_always_writes_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / "settings.json"
    monkeypatch.setattr(
        "orion_agent.permissions.persistence._settings_path_for_scope",
        lambda scope: f,
    )
    written = persist_decision_if_always(
        decision_str="always_allow", tool_name="Bash",
    )
    assert written is True
    rules = list_permission_rules(settings_file=f)
    assert rules[0].tool_name == "Bash"
    assert rules[0].decision == "allow"


def test_persist_decision_if_always_writes_deny(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / "settings.json"
    monkeypatch.setattr(
        "orion_agent.permissions.persistence._settings_path_for_scope",
        lambda scope: f,
    )
    persist_decision_if_always(decision_str="always_deny", tool_name="Bash")
    rules = list_permission_rules(settings_file=f)
    assert rules[0].decision == "deny"


def test_persist_decision_skips_one_off() -> None:
    """allow / deny(非 always_*)→ 不寫 rule。"""
    assert persist_decision_if_always(
        decision_str="allow", tool_name="Bash",
    ) is False


def test_find_matching_rule_user_scope(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    f = tmp_path / "settings.json"
    monkeypatch.setattr(
        "orion_agent.permissions.persistence._settings_path_for_scope",
        lambda scope: f,
    )
    add_permission_rule(
        PermissionRule(tool_name="Edit", decision="allow"),
    )
    found = find_matching_rule("Edit", {})
    assert found is not None
    assert found.decision == "allow"


def test_find_matching_rule_deny_wins_over_allow(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 scope deny 比 allow 優先。"""
    f = tmp_path / "settings.json"
    monkeypatch.setattr(
        "orion_agent.permissions.persistence._settings_path_for_scope",
        lambda scope: f,
    )
    add_permission_rule(PermissionRule(tool_name="X", decision="allow"))
    add_permission_rule(PermissionRule(tool_name="X", decision="deny"))
    found = find_matching_rule("X", {})
    assert found is not None
    assert found.decision == "deny"


def test_find_no_match() -> None:
    assert find_matching_rule("NeverHeardOfIt", {}) is None
