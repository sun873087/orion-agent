"""AppState / ToolPermissionContext / IDEContext 測試。"""

from __future__ import annotations

from pathlib import Path

from orion_sdk.state.app_state import (
    AppState,
    IDEContext,
    ToolPermissionContext,
)


def test_default_app_state() -> None:
    s = AppState()
    assert isinstance(s.tool_permission_context, ToolPermissionContext)
    assert isinstance(s.ide_context, IDEContext)
    assert s.mcp_server_statuses == {}
    assert s.pending_attachments == []
    assert not s.tool_permission_context.bypass_permissions


def test_grant_tool_immutable() -> None:
    s = AppState()
    original = s.tool_permission_context
    s.grant_tool("Bash", "ls *")
    assert s.tool_permission_context is not original
    assert s.is_tool_granted("Bash", "ls *")
    assert not s.is_tool_granted("Bash", "rm -rf /")


def test_grant_dedup() -> None:
    s = AppState()
    s.grant_tool("Bash", "ls *")
    ref = s.tool_permission_context
    s.grant_tool("Bash", "ls *") # 重複
    # 重複 grant 應 short-circuit,context 不變
    assert s.tool_permission_context is ref


def test_deny_tool() -> None:
    s = AppState()
    s.deny_tool("Bash", "rm -rf /")
    assert s.is_tool_denied("Bash", "rm -rf /")
    assert not s.is_tool_denied("Bash", "ls")


def test_bypass_permissions() -> None:
    pc = ToolPermissionContext(bypass_permissions=True)
    s = AppState(tool_permission_context=pc)
    assert s.is_tool_granted("Anything", "anything")


def test_additional_working_directories(tmp_path: Path) -> None:
    s = AppState()
    s.add_working_directory(tmp_path)
    assert tmp_path in s.tool_permission_context.additional_working_directories
    # 重加 dedup
    s.add_working_directory(tmp_path)
    assert s.tool_permission_context.additional_working_directories.count(tmp_path) == 1


def test_mcp_status() -> None:
    s = AppState()
    s.set_mcp_status("github", "connected")
    s.set_mcp_status("slack", "failed")
    assert s.mcp_server_statuses == {"github": "connected", "slack": "failed"}
    s.set_mcp_status("github", "disconnected")
    assert s.mcp_server_statuses["github"] == "disconnected"


def test_ide_context_default_disconnected() -> None:
    s = AppState()
    assert s.ide_context.connected is False
    assert s.ide_context.selection is None


def test_tool_permission_context_frozen() -> None:
    """ToolPermissionContext 是 frozen — replace 是唯一更新路徑。"""
    pc = ToolPermissionContext()
    pc2 = pc.with_grant("X", "p")
    assert pc is not pc2
    assert pc.granted == {}
    assert pc2.granted == {"X": ("p",)}
