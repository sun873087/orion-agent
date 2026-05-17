"""Permission policy engine — Claude Code 風 allowlist / denylist。

對應 `~/.orion/permissions.json`(全域)+ `<workspace>/.orion/
permissions.json`(專案)。can_use_tool 先讀 policy:deny 命中 → DENY,allow
命中 → ALLOW,都不命中 → 'ask' 回去走 mode-based 行為(Ask 模式顯 banner、
Act 模式 allow)。

Pattern 語法(對齊 Claude Code):
- `ToolName`              — 任何 input 的 ToolName 都 match
- `ToolName(arg_pattern)` — arg_pattern 對 tool 的「主要參數」走 fnmatch glob
                            (`*` 任意字元,`?` 任意一字元)
- `WebFetch(domain:host)` — 特例,對 url 的 hostname 做 fnmatch

主要參數對應表見 `_KEY_ARG`。沒列在 _KEY_ARG 的工具 parens 內 pattern 一律不會
match — 想針對它就用無 parens 寫法。
"""

from __future__ import annotations

import fnmatch
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


def _global_policy_path() -> Path:
    return Path.home() / ".orion" / "permissions.json"


def _project_policy_path(workspace_dir: Path) -> Path:
    return workspace_dir / ".orion" / "permissions.json"


@dataclass
class Policy:
    """allow / deny 兩列。deny 永遠勝過 allow。"""

    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, list[str]]:
        return {"allow": list(self.allow), "deny": list(self.deny)}

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Policy:
        def _strings(v: Any) -> list[str]:
            if not isinstance(v, list):
                return []
            return [s for s in v if isinstance(s, str)]

        return cls(allow=_strings(d.get("allow")), deny=_strings(d.get("deny")))


def _read_policy_file(path: Path) -> Policy:
    if not path.is_file():
        return Policy()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return Policy()
    if not isinstance(data, dict):
        return Policy()
    return Policy.from_dict(data)


def load_policy(workspace_dir: Path | None) -> Policy:
    """合併 global + project policy(若有 workspace_dir)。

    Allow 兩邊串接,deny 兩邊串接;deny 永遠優先(decide 內邏輯)。
    任一檔案不存在或讀失敗就視為空 policy,不擋使用者。
    """
    g = _read_policy_file(_global_policy_path())
    if workspace_dir is None:
        return g
    p = _read_policy_file(_project_policy_path(workspace_dir))
    return Policy(allow=g.allow + p.allow, deny=g.deny + p.deny)


def load_scope(scope: str, workspace_dir: Path | None) -> Policy:
    """Load 單一 scope 的 policy(給 RPC 讀單獨 scope 用,設定 UI 編輯前)。"""
    if scope == "global":
        return _read_policy_file(_global_policy_path())
    if scope == "project":
        if workspace_dir is None:
            return Policy()
        return _read_policy_file(_project_policy_path(workspace_dir))
    raise ValueError(f"unknown scope: {scope!r}")


def save_policy(
    policy: Policy,
    *,
    scope: str,
    workspace_dir: Path | None = None,
) -> None:
    if scope == "global":
        target = _global_policy_path()
    elif scope == "project":
        if workspace_dir is None:
            raise ValueError("workspace_dir required for project scope")
        target = _project_policy_path(workspace_dir)
    else:
        raise ValueError(f"unknown scope: {scope!r}")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(policy.to_dict(), indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


# Per-tool「主要參數」— pattern in parens 用這 key 的值做 fnmatch。
_KEY_ARG: dict[str, str] = {
    "Bash": "command",
    "Read": "path",
    "Write": "path",
    "Edit": "path",
    "NotebookEdit": "notebook_path",
    "Glob": "pattern",
    "Grep": "pattern",
    "WebFetch": "url",
    "WebSearch": "query",
    "open_url": "url",
    "open_path": "path",
}


def _parse_pattern(pattern: str) -> tuple[str, str | None]:
    """`Bash(uv run *)` → ('Bash', 'uv run *');`WebSearch` → ('WebSearch', None)。"""
    if pattern.endswith(")") and "(" in pattern:
        name, _, rest = pattern.partition("(")
        return name.strip(), rest[:-1]
    return pattern.strip(), None


def matches(pattern: str, tool_name: str, tool_input: dict[str, Any]) -> bool:
    """單條 pattern 對單次 tool call 是否 match。"""
    name_part, arg_pattern = _parse_pattern(pattern)
    if name_part != tool_name:
        return False
    if arg_pattern is None:
        return True
    # WebFetch(domain:host)
    if arg_pattern.startswith("domain:"):
        host_pattern = arg_pattern[len("domain:") :].strip()
        url = tool_input.get("url")
        if not isinstance(url, str):
            return False
        try:
            host = urlparse(url).hostname or ""
        except Exception:  # noqa: BLE001
            return False
        return fnmatch.fnmatchcase(host, host_pattern)
    # 一般:主要參數 fnmatch
    key = _KEY_ARG.get(tool_name)
    if key is None:
        return False
    val = tool_input.get(key)
    if not isinstance(val, str):
        return False
    return fnmatch.fnmatchcase(val, arg_pattern)


def decide(
    policy: Policy,
    tool_name: str,
    tool_input: dict[str, Any],
) -> str:
    """回 'deny' | 'allow' | 'ask'。deny 永遠勝。"""
    for p in policy.deny:
        if matches(p, tool_name, tool_input):
            return "deny"
    for p in policy.allow:
        if matches(p, tool_name, tool_input):
            return "allow"
    return "ask"
