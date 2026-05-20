"""Permission rule 持久化。

對應 TS Claude Code `src/services/policyLimits/`(rule 加入 + 比對)。

當 user 在 ws permission ask 選 "Always Allow" / "Always Deny",把該決策寫進
settings 的 `permissions.rules` 陣列。新對話遇同 tool 直接套用,不再問。

Settings 三層:
- `user`(`~/.orion/settings.json`)— 全域,跨 project
- `project`(`<cwd>/.orion/settings.json`)— commit 進 repo,團隊共享
- `local`(`<cwd>/.orion/settings.local.json`)— gitignored,個人 dev override

範圍:**user** layer(不引入 project/local 概念,sources 已知時可擴)。
比對只看 `tool_name`(spec § 8 踩雷 #3 提醒:複雜 matcher 留給未來)。
"""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Literal

from orion_sdk.settings import (
    load_settings,
    save_settings,
    settings_path,
)

PermissionRuleDecision = Literal["allow", "deny"]
PermissionScope = Literal["user", "project", "local"]


@dataclass(frozen=True)
class PermissionRule:
    """單一 permission 規則。

    範圍只看 `tool_name`(沒 matcher);未來 可加 input pattern matcher
    (例:`{command_starts_with: "ls"}`)。
    """

    tool_name: str
    decision: PermissionRuleDecision
    matcher: dict[str, Any] | None = None
    """進階比對條件(不用,僅佔位)。"""

    note: str = ""
    """user 寫的備註(從哪個對話來的等)。"""


def _settings_path_for_scope(scope: PermissionScope) -> Path:
    """三 scope 各自的 settings 檔位置。

    scope:
      - user → `$ORION_HOME/settings.json`(預設 `~/.orion/`)
      - project → `<cwd>/.orion/settings.json`
      - local → `<cwd>/.orion/settings.local.json`
    """
    if scope == "user":
        return settings_path()
    cwd = Path.cwd()
    base = cwd / ".orion"
    if scope == "project":
        return base / "settings.json"
    return base / "settings.local.json" # local


def _ensure_rules_block(settings: dict[str, Any]) -> list[dict[str, Any]]:
    """確保 `settings.permissions.rules` 是 list,回該 list 的 ref。"""
    perms = settings.get("permissions")
    if not isinstance(perms, dict):
        perms = {}
        settings["permissions"] = perms
    rules = perms.get("rules")
    if not isinstance(rules, list):
        rules = []
        perms["rules"] = rules
    return rules


def _rule_to_dict(rule: PermissionRule) -> dict[str, Any]:
    d = asdict(rule)
    # 拋掉空字串 / None 欄位,讓 settings.json 比較乾淨
    if not d.get("matcher"):
        d.pop("matcher", None)
    if not d.get("note"):
        d.pop("note", None)
    return d


def _rules_match(a: dict[str, Any], b: dict[str, Any]) -> bool:
    """是否同條規則(避免重複 append)。

    比對 tool_name + decision + matcher;note 不參與比對(同 rule 不同 note 視為同條)。
    """
    return (
        a.get("tool_name") == b.get("tool_name")
        and a.get("decision") == b.get("decision")
        and (a.get("matcher") or None) == (b.get("matcher") or None)
    )


def add_permission_rule(
    rule: PermissionRule,
    *,
    scope: PermissionScope = "user",
    settings_file: Path | None = None,
) -> bool:
    """寫一條 rule 到對應 scope 的 settings。

    Args:
        rule: 要加的規則。
        scope: user / project / local。
        settings_file: 測試覆寫;production 用 scope 對應的預設位置。

    Returns:
        bool — True 表示新加(或檔不存在 → 建並寫),False 表示已存在(冪等)。
    """
    sp = settings_file or _settings_path_for_scope(scope)
    settings = load_settings(sp)
    rules = _ensure_rules_block(settings)

    rule_dict = _rule_to_dict(rule)
    if any(_rules_match(existing, rule_dict) for existing in rules):
        return False # 已存在 — no-op

    rules.append(rule_dict)
    save_settings(settings, sp)
    return True


def remove_permission_rule(
    tool_name: str,
    *,
    decision: PermissionRuleDecision | None = None,
    scope: PermissionScope = "user",
    settings_file: Path | None = None,
) -> int:
    """移除符合條件的 rule(s)。

    Args:
        tool_name: 必填,只移除此工具的 rule。
        decision: 若指定,只移該 decision 的 rule;None 表示兩種都清。
        scope / settings_file: 同 add_permission_rule。

    Returns:
        移除的 rule 數量。
    """
    sp = settings_file or _settings_path_for_scope(scope)
    settings = load_settings(sp)
    rules = _ensure_rules_block(settings)

    keep: list[dict[str, Any]] = []
    removed = 0
    for r in rules:
        if r.get("tool_name") != tool_name:
            keep.append(r)
            continue
        if decision is not None and r.get("decision") != decision:
            keep.append(r)
            continue
        removed += 1

    if removed == 0:
        return 0
    settings["permissions"]["rules"] = keep
    save_settings(settings, sp)
    return removed


def list_permission_rules(
    *,
    scope: PermissionScope = "user",
    settings_file: Path | None = None,
) -> list[PermissionRule]:
    """列出 scope 下所有 rule。"""
    sp = settings_file or _settings_path_for_scope(scope)
    settings = load_settings(sp)
    rules = _ensure_rules_block(settings)
    out: list[PermissionRule] = []
    for r in rules:
        if not isinstance(r, dict):
            continue
        tn = r.get("tool_name")
        dec = r.get("decision")
        if not isinstance(tn, str) or dec not in ("allow", "deny"):
            continue
        out.append(
            PermissionRule(
                tool_name=tn,
                decision=dec,
                matcher=r.get("matcher"),
                note=str(r.get("note") or ""),
            )
        )
    return out


def find_matching_rule(
    tool_name: str,
    tool_input: dict[str, Any], # noqa: ARG001 不用 input,留接口
    *,
    scopes: tuple[PermissionScope, ...] = ("local", "project", "user"),
) -> PermissionRule | None:
    """找第一條 matching rule(deny 優先於 allow,scope 由近而遠)。

    順序:
      1. local → project → user(近 scope 蓋遠 scope)
      2. 同 scope 內:deny 先於 allow(deny 一旦 match 就不會被 allow 推翻)

    範圍只比對 `tool_name`,沒 input matcher。
    """
    for scope in scopes:
        rules = list_permission_rules(scope=scope)
        denies = [r for r in rules if r.tool_name == tool_name and r.decision == "deny"]
        if denies:
            return denies[0]
        allows = [r for r in rules if r.tool_name == tool_name and r.decision == "allow"]
        if allows:
            return allows[0]
    return None


# ─── ws permission integration helper ───────────────────────────────────────


def persist_decision_if_always(
    *,
    decision_str: str,
    tool_name: str,
    note: str = "",
    scope: PermissionScope | None = None,
) -> bool:
    """把 ws permission ask 收到的 decision 字串轉成持久化 rule(若是 always_*)。

    用在 `make_can_use_tool_for_websocket` 的 decision 處理之後 — 收到
    `always_allow` / `always_deny` 時呼叫本函式,回 True 表示確實寫了 rule。

    Args:
        decision_str: ws 收到的 raw decision(allow / deny / always_allow / always_deny)。
        tool_name: 該次 ask 的工具名。
        note: 寫進 rule 的備註。
        scope: 預設由 `ORION_PERMISSION_RULE_SCOPE` env 決定,fallback "user"。

    Returns:
        True: 真的寫了一條 rule;False: decision 不是 always_*,或 rule 已存在。
    """
    if decision_str not in ("always_allow", "always_deny"):
        return False

    target_scope: PermissionScope = scope or _scope_from_env()
    actual_decision: PermissionRuleDecision = (
        "allow" if decision_str == "always_allow" else "deny"
    )
    rule = PermissionRule(
        tool_name=tool_name,
        decision=actual_decision,
        note=note,
    )
    return add_permission_rule(rule, scope=target_scope)


def _scope_from_env() -> PermissionScope:
    raw = os.environ.get("ORION_PERMISSION_RULE_SCOPE", "user").lower()
    if raw in ("local", "project", "user"):
        return raw # type: ignore[return-value]
    return "user"


__all__ = [
    "PermissionRule",
    "PermissionRuleDecision",
    "PermissionScope",
    "add_permission_rule",
    "find_matching_rule",
    "list_permission_rules",
    "persist_decision_if_always",
    "remove_permission_rule",
]
