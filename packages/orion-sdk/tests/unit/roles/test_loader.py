"""Pane role loader unit tests。"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest

from orion_sdk.roles.loader import (
    Role,
    _bundled_roles,
    load_all_roles,
    load_roles_dir,
)


def test_bundled_roles_present():
    """4 個 bundled defaults 必須能載出來。"""
    bundled = _bundled_roles()
    names = {r.name for r in bundled}
    assert "researcher" in names
    assert "coder" in names
    assert "reviewer" in names
    assert "doc-writer" in names


def test_bundled_roles_have_descriptions():
    bundled = _bundled_roles()
    for r in bundled:
        assert r.description, f"role {r.name} missing description"
        assert r.body.strip(), f"role {r.name} missing body"


def test_bundled_researcher_disables_write_tools():
    """researcher 應預設關掉 Edit/Write/Bash。"""
    bundled = _bundled_roles()
    by_name = {r.name: r for r in bundled}
    researcher = by_name["researcher"]
    assert "Edit" in researcher.default_disabled_tools
    assert "Write" in researcher.default_disabled_tools
    assert "Bash" in researcher.default_disabled_tools


def test_bundled_coder_does_not_disable_write_tools():
    """coder 不該預設關 Edit/Write/Bash(它要會寫 code 跑 test)。"""
    bundled = _bundled_roles()
    by_name = {r.name: r for r in bundled}
    coder = by_name["coder"]
    assert "Edit" not in coder.default_disabled_tools
    assert "Write" not in coder.default_disabled_tools
    assert "Bash" not in coder.default_disabled_tools


def test_load_roles_dir_empty():
    """空目錄回 []。"""
    with tempfile.TemporaryDirectory() as d:
        assert load_roles_dir(Path(d)) == []


def test_load_roles_dir_with_role():
    """寫個 ROLE.md 進去 → load_roles_dir 應該載到。"""
    with tempfile.TemporaryDirectory() as d:
        role_dir = Path(d) / "my-role"
        role_dir.mkdir()
        (role_dir / "ROLE.md").write_text(
            "---\n"
            "name: my-role\n"
            "description: test\n"
            "default_disabled_tools: Bash\n"
            "---\n\n"
            "Hello world",
            encoding="utf-8",
        )
        roles = load_roles_dir(Path(d))
        assert len(roles) == 1
        r = roles[0]
        assert r.name == "my-role"
        assert r.description == "test"
        assert r.default_disabled_tools == ["Bash"]
        assert "Hello world" in r.body


def test_load_roles_dir_csv_string_for_disabled_tools():
    """default_disabled_tools 接受 CSV string。"""
    with tempfile.TemporaryDirectory() as d:
        role_dir = Path(d) / "x"
        role_dir.mkdir()
        (role_dir / "ROLE.md").write_text(
            "---\n"
            "name: x\n"
            "default_disabled_tools: Edit,Write, Bash\n"
            "---\n\nbody",
            encoding="utf-8",
        )
        r = load_roles_dir(Path(d))[0]
        assert r.default_disabled_tools == ["Edit", "Write", "Bash"]


def test_load_roles_dir_invalid_permission_mode():
    """無效 permission_mode 視為 None。"""
    with tempfile.TemporaryDirectory() as d:
        role_dir = Path(d) / "x"
        role_dir.mkdir()
        (role_dir / "ROLE.md").write_text(
            "---\n"
            "name: x\n"
            "default_permission_mode: garbage\n"
            "---\n\nbody",
            encoding="utf-8",
        )
        r = load_roles_dir(Path(d))[0]
        assert r.default_permission_mode is None


def test_load_all_roles_user_overrides_bundled(monkeypatch):
    """User 目錄同名 role 覆蓋 bundled。"""
    with tempfile.TemporaryDirectory() as d:
        users_root = Path(d) / "users"
        user_dir = users_root / "cowork-local" / "roles" / "coder"
        user_dir.mkdir(parents=True)
        (user_dir / "ROLE.md").write_text(
            "---\nname: coder\ndescription: USER OVERRIDE\n---\n\noverride body",
            encoding="utf-8",
        )
        monkeypatch.setenv("ORION_USER_ROLES_DIR", str(users_root))
        roles = load_all_roles(user_id="cowork-local")
        by_name = {r.name: r for r in roles}
        assert by_name["coder"].description == "USER OVERRIDE"
        assert "override body" in by_name["coder"].body


def test_load_all_roles_no_user_id():
    """user_id=None 只回 bundled。"""
    roles = load_all_roles(user_id=None)
    assert len(roles) >= 4
    for r in roles:
        assert r.source_path is not None
        assert "/bundled/" in str(r.source_path)


def test_role_dataclass_default_perm_none_ok():
    """default_permission_mode 可為 None。"""
    r = Role(name="x")
    assert r.default_permission_mode is None
    assert r.default_disabled_tools == []
