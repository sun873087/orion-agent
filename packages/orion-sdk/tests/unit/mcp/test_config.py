"""mcp/config.py — 載入優先順序 + 合併。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from orion_sdk.mcp.config import (
    HttpMcpConfig,
    StdioMcpConfig,
    load_mcp_config,
)


def _write_config(path: Path, servers: dict) -> None:  # noqa: ANN001
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"mcpServers": servers}), encoding="utf-8")


def test_no_config_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: tmp_path / "fakehome")
    cfg = load_mcp_config(cwd=tmp_path)
    assert cfg == {}


def test_global_config_loaded(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: home)
    _write_config(
        home / ".orion" / "mcp.json",
        {"fs": {"type": "stdio", "command": "echo", "args": ["hi"]}},
    )
    cfg = load_mcp_config(cwd=tmp_path)
    assert "fs" in cfg
    assert isinstance(cfg["fs"], StdioMcpConfig)
    assert cfg["fs"].command == "echo"


def test_cwd_overrides_global(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: home)
    _write_config(
        home / ".orion" / "mcp.json",
        {"fs": {"type": "stdio", "command": "echo", "args": ["global"]}},
    )
    proj = tmp_path / "proj"
    proj.mkdir()
    _write_config(
        proj / ".orion" / "mcp.json",
        {"fs": {"type": "stdio", "command": "echo", "args": ["project"]}},
    )
    cfg = load_mcp_config(cwd=proj)
    assert cfg["fs"].args == ["project"]


def test_extra_config_overrides_all(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: home)
    _write_config(
        home / ".orion" / "mcp.json",
        {"fs": {"type": "stdio", "command": "echo", "args": ["a"]}},
    )
    _write_config(
        tmp_path / ".orion" / "mcp.json",
        {"fs": {"type": "stdio", "command": "echo", "args": ["b"]}},
    )
    extra = tmp_path / "explicit.json"
    _write_config(extra, {"fs": {"type": "stdio", "command": "echo", "args": ["c"]}})
    cfg = load_mcp_config(cwd=tmp_path, extra_path=extra)
    assert cfg["fs"].args == ["c"]


def test_corrupt_json_returns_empty(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: home)
    bad = home / ".orion" / "mcp.json"
    bad.parent.mkdir(parents=True)
    bad.write_text("{ not valid json", encoding="utf-8")
    cfg = load_mcp_config(cwd=tmp_path)
    assert cfg == {}


def test_unknown_type_skipped(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: home)
    _write_config(
        home / ".orion" / "mcp.json",
        {
            "ok": {"type": "stdio", "command": "echo"},
            "weird": {"type": "websocket", "url": "wss://x"},
        },
    )
    cfg = load_mcp_config(cwd=tmp_path)
    assert "ok" in cfg
    assert "weird" not in cfg


def test_http_type_parsed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path / "fakehome"
    monkeypatch.setattr("orion_sdk.mcp.config.Path.home", lambda: home)
    _write_config(
        home / ".orion" / "mcp.json",
        {"remote": {"type": "http", "url": "https://example.com/mcp"}},
    )
    cfg = load_mcp_config(cwd=tmp_path)
    assert isinstance(cfg["remote"], HttpMcpConfig)
    assert cfg["remote"].url == "https://example.com/mcp"
