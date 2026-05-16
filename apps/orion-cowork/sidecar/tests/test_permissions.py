"""Unit tests for orion_cowork_sidecar.permissions — Claude Code 風 allowlist。

只測 pattern matcher + decide;file I/O 跑 tmp_path 避免污染 ~/.orion-cowork。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_cowork_sidecar import permissions as perm


# ─── Pattern matching ───────────────────────────────────────────────────────


def test_bare_toolname_matches_any_call() -> None:
    assert perm.matches("WebSearch", "WebSearch", {"query": "anything"}) is True
    assert perm.matches("WebSearch", "WebSearch", {}) is True


def test_bare_toolname_does_not_cross_match() -> None:
    assert perm.matches("WebSearch", "WebFetch", {"query": "x"}) is False


def test_paren_pattern_glob_on_key_arg() -> None:
    assert perm.matches("Bash(uv run *)", "Bash", {"command": "uv run pytest"}) is True
    assert perm.matches("Bash(uv run *)", "Bash", {"command": "uv pip install"}) is False
    assert perm.matches("Bash(uv *)", "Bash", {"command": "uv pip install"}) is True


def test_paren_pattern_path_glob() -> None:
    assert perm.matches("Read(/tmp/*)", "Read", {"path": "/tmp/foo.log"}) is True
    # fnmatch 的 * 也吃 / — recursive 一般用 ** 但 fnmatchcase 對 * 沒目錄限制
    assert perm.matches("Read(/tmp/*)", "Read", {"path": "/tmp/sub/foo.log"}) is True
    assert perm.matches("Read(/tmp/*)", "Read", {"path": "/var/foo.log"}) is False


def test_webfetch_domain_special() -> None:
    pat = "WebFetch(domain:docs.anthropic.com)"
    assert perm.matches(pat, "WebFetch", {"url": "https://docs.anthropic.com/foo"}) is True
    assert perm.matches(pat, "WebFetch", {"url": "https://docs.anthropic.com"}) is True
    assert perm.matches(pat, "WebFetch", {"url": "https://example.com/docs.anthropic.com"}) is False


def test_webfetch_domain_glob() -> None:
    pat = "WebFetch(domain:*.anthropic.com)"
    assert perm.matches(pat, "WebFetch", {"url": "https://docs.anthropic.com/x"}) is True
    assert perm.matches(pat, "WebFetch", {"url": "https://api.anthropic.com/x"}) is True
    assert perm.matches(pat, "WebFetch", {"url": "https://anthropic.com/x"}) is False


def test_unknown_tool_with_paren_does_not_match() -> None:
    # mcp__... 沒在 _KEY_ARG 內,parens pattern 無法 match;但 bare name 可以
    assert perm.matches("mcp__server__tool(*)", "mcp__server__tool", {"x": "y"}) is False
    assert perm.matches("mcp__server__tool", "mcp__server__tool", {"x": "y"}) is True


def test_paren_missing_arg_key_in_input() -> None:
    # Bash 期望 command,但 input 沒給 → 不 match
    assert perm.matches("Bash(*)", "Bash", {}) is False


# ─── decide() three-state ────────────────────────────────────────────────────


def test_decide_returns_ask_when_no_match() -> None:
    pol = perm.Policy(allow=["Read"], deny=["Bash"])
    assert perm.decide(pol, "WebFetch", {"url": "x"}) == "ask"


def test_decide_allow_match() -> None:
    pol = perm.Policy(allow=["WebSearch", "Bash(npm *)"], deny=[])
    assert perm.decide(pol, "WebSearch", {}) == "allow"
    assert perm.decide(pol, "Bash", {"command": "npm test"}) == "allow"


def test_decide_deny_match() -> None:
    pol = perm.Policy(allow=[], deny=["Bash(rm -rf *)"])
    assert perm.decide(pol, "Bash", {"command": "rm -rf /tmp/junk"}) == "deny"


def test_deny_overrides_allow() -> None:
    pol = perm.Policy(allow=["Bash"], deny=["Bash(rm -rf *)"])
    assert perm.decide(pol, "Bash", {"command": "ls"}) == "allow"
    assert perm.decide(pol, "Bash", {"command": "rm -rf foo"}) == "deny"


# ─── File I/O + scope merging ────────────────────────────────────────────────


def test_save_and_load_global(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    # 用 tmp_path 當假 home,不污染真 ~
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[arg-type]
    pol = perm.Policy(allow=["WebSearch", "Read"], deny=["Bash(sudo *)"])
    perm.save_policy(pol, scope="global")
    written = tmp_path / ".orion-cowork" / "permissions.json"
    assert written.is_file()
    data = json.loads(written.read_text())
    assert data["allow"] == ["WebSearch", "Read"]
    assert data["deny"] == ["Bash(sudo *)"]
    # load_scope 拿得回來
    loaded = perm.load_scope("global", None)
    assert loaded.allow == ["WebSearch", "Read"]
    assert loaded.deny == ["Bash(sudo *)"]


def test_load_policy_merges_global_and_project(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[arg-type]
    # global
    perm.save_policy(perm.Policy(allow=["WebSearch"], deny=["Bash(sudo *)"]), scope="global")
    # project
    ws = tmp_path / "workspace"
    ws.mkdir()
    perm.save_policy(
        perm.Policy(allow=["Read", "Grep"], deny=[]),
        scope="project",
        workspace_dir=ws,
    )
    merged = perm.load_policy(ws)
    assert set(merged.allow) == {"WebSearch", "Read", "Grep"}
    assert merged.deny == ["Bash(sudo *)"]


def test_missing_file_returns_empty_policy(tmp_path: Path) -> None:
    # No file exists in this scope
    pol = perm.load_scope("project", tmp_path)
    assert pol.allow == []
    assert pol.deny == []


def test_malformed_json_does_not_crash(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))  # type: ignore[arg-type]
    (tmp_path / ".orion-cowork").mkdir()
    (tmp_path / ".orion-cowork" / "permissions.json").write_text("not json {{{", encoding="utf-8")
    pol = perm.load_scope("global", None)
    assert pol.allow == []
    assert pol.deny == []
