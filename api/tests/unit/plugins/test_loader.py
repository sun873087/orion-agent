"""plugins.loader — discover_plugins + load_all_plugins + enable/disable。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_agent.hooks.registry import HookRegistry
from orion_agent.plugins.loader import (
    disable_plugin,
    discover_plugins,
    enable_plugin,
    get_enabled_plugins,
    load_all_plugins,
)


def _write_manifest(plugin_dir: Path, data: dict) -> None:
    plugin_dir.mkdir(parents=True, exist_ok=True)
    (plugin_dir / "plugin.json").write_text(json.dumps(data), encoding="utf-8")


def test_discover_empty(tmp_path: Path) -> None:
    assert discover_plugins([tmp_path]) == []


def test_discover_basic(tmp_path: Path) -> None:
    _write_manifest(
        tmp_path / "p1",
        {"name": "p1", "version": "1.0.0", "description": "first"},
    )
    _write_manifest(
        tmp_path / "p2",
        {
            "name": "p2",
            "skills": ["skills/x.md"],
            "hooks": [{"event": "PostToolUse", "webhook": "https://x"}],
            "mcp_servers": {"github": {"command": "node"}},
        },
    )
    plugins = discover_plugins([tmp_path])
    by_name = {p.name: p for p in plugins}
    assert set(by_name) == {"p1", "p2"}
    assert by_name["p1"].description == "first"
    assert by_name["p2"].skills == ["skills/x.md"]
    assert by_name["p2"].mcp_servers == {"github": {"command": "node"}}


def test_discover_invalid_json_skipped(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bad"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text("{not json", encoding="utf-8")
    assert discover_plugins([tmp_path]) == []


def test_discover_missing_name_skipped(tmp_path: Path) -> None:
    plugin_dir = tmp_path / "bad"
    plugin_dir.mkdir()
    (plugin_dir / "plugin.json").write_text(json.dumps({"version": "1"}), encoding="utf-8")
    assert discover_plugins([tmp_path]) == []


def test_get_enabled_plugins() -> None:
    assert get_enabled_plugins({}) == set()
    assert get_enabled_plugins({"enabledPlugins": ["a", "b"]}) == {"a", "b"}
    assert get_enabled_plugins({"enabledPlugins": "not-list"}) == set()


def test_enable_disable_plugin() -> None:
    s: dict = {}
    enable_plugin(s, "p1")
    assert s["enabledPlugins"] == ["p1"]
    enable_plugin(s, "p1")  # idempotent
    assert s["enabledPlugins"] == ["p1"]
    enable_plugin(s, "p2")
    assert s["enabledPlugins"] == ["p1", "p2"]
    disable_plugin(s, "p1")
    assert s["enabledPlugins"] == ["p2"]
    disable_plugin(s, "no-such")  # no-op
    assert s["enabledPlugins"] == ["p2"]


def test_load_all_plugins_only_enabled(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_PLUGINS_DIR", str(tmp_path / "no-such"))
    _write_manifest(
        tmp_path / "p1",
        {"name": "p1", "hooks": [{"event": "PreToolUse", "webhook": "https://x"}]},
    )
    _write_manifest(
        tmp_path / "p2",
        {"name": "p2", "hooks": [{"event": "PostToolUse", "webhook": "https://y"}]},
    )

    reg = HookRegistry()
    res = load_all_plugins(
        {"enabledPlugins": ["p1"]},
        hook_registry=reg,
        extra_roots=[tmp_path],
    )
    assert {p.name for p in res.loaded} == {"p1"}
    assert reg.count("PreToolUse") == 1
    assert reg.count("PostToolUse") == 0  # p2 not enabled


def test_load_all_plugins_collects_skill_dirs(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_PLUGINS_DIR", str(tmp_path / "no-such"))
    plugin_dir = tmp_path / "ghp"
    skills_dir = plugin_dir / "skills"
    skills_dir.mkdir(parents=True)
    (skills_dir / "review.md").write_text("---\nname: review\n---\nbody", encoding="utf-8")
    _write_manifest(
        plugin_dir,
        {"name": "ghp", "skills": ["skills/review.md"]},
    )

    reg = HookRegistry()
    res = load_all_plugins(
        {"enabledPlugins": ["ghp"]},
        hook_registry=reg,
        extra_roots=[tmp_path],
    )
    assert any(d == skills_dir for d in res.skill_dirs)


def test_load_all_plugins_collects_mcp_servers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_PLUGINS_DIR", str(tmp_path / "no-such"))
    _write_manifest(
        tmp_path / "ghp",
        {
            "name": "ghp",
            "mcp_servers": {"gh": {"command": "node"}},
        },
    )

    reg = HookRegistry()
    res = load_all_plugins(
        {"enabledPlugins": ["ghp"]},
        hook_registry=reg,
        extra_roots=[tmp_path],
    )
    assert "ghp__gh" in res.mcp_servers
    assert res.mcp_servers["ghp__gh"] == {"command": "node"}


def test_load_all_plugins_web_only_blocks_shell(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_PLUGINS_DIR", str(tmp_path / "no-such"))
    _write_manifest(
        tmp_path / "p1",
        {
            "name": "p1",
            "hooks": [
                {"event": "PreToolUse", "command": "echo bad"},
                {"event": "PostToolUse", "webhook": "https://ok"},
            ],
        },
    )

    reg = HookRegistry()
    res = load_all_plugins(
        {"enabledPlugins": ["p1"]},
        hook_registry=reg,
        web_only=True,
        extra_roots=[tmp_path],
    )
    assert res.hooks_registered == 1
    assert reg.count("PreToolUse") == 0
    assert reg.count("PostToolUse") == 1
