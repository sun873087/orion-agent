"""Sidecar role.* RPC e2e — sub-process spawn 驗證 CRUD。"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest


def _run_sidecar(input_lines: list[str], data_dir: str, timeout: float = 15.0) -> list[dict]:
    env = dict(os.environ)
    env["ORION_COWORK_DATA_DIR"] = data_dir
    env["ORION_USER_ROLES_DIR"] = f"{data_dir}/users"
    proc = subprocess.run(
        [sys.executable, "-m", "orion_cowork_sidecar"],
        input="\n".join(input_lines) + "\n",
        capture_output=True,
        text=True,
        timeout=timeout,
        env=env,
    )
    return [json.loads(line) for line in proc.stdout.strip().split("\n") if line]


@pytest.fixture
def data_dir():
    with tempfile.TemporaryDirectory(prefix="cowork-role-rpc-") as d:
        yield d


def test_role_list_includes_bundled(data_dir: str) -> None:
    """新環境 → role.list 至少回 4 個 bundled。"""
    frames = _run_sidecar([
        '{"id":"l","method":"role.list"}',
    ], data_dir)
    listed = next(f for f in frames if f.get("id") == "l")
    assert listed["event"] == "role_list"
    names = {r["name"] for r in listed["data"]["roles"]}
    assert {"researcher", "coder", "reviewer", "doc-writer"}.issubset(names)
    # 全為 bundled source(沒寫過 user roles)
    for r in listed["data"]["roles"]:
        assert r["source"] == "bundled"
        assert r["editable"] is False


def test_role_write_then_list_shows_user_role(data_dir: str) -> None:
    """寫一個 user role → list 看得到 + source=user + editable=True。"""
    _run_sidecar([
        '{"id":"w","method":"role.write","params":'
        '{"name":"my-role","body":"custom body","description":"my custom",'
        '"default_disabled_tools":"Bash,Edit"}}',
    ], data_dir)
    frames = _run_sidecar([
        '{"id":"l","method":"role.list"}',
    ], data_dir)
    listed = next(f for f in frames if f.get("id") == "l")
    by_name = {r["name"]: r for r in listed["data"]["roles"]}
    assert "my-role" in by_name
    assert by_name["my-role"]["source"] == "user"
    assert by_name["my-role"]["editable"] is True
    assert by_name["my-role"]["description"] == "my custom"
    assert "Bash" in by_name["my-role"]["default_disabled_tools"]
    assert "Edit" in by_name["my-role"]["default_disabled_tools"]


def test_role_get_returns_body(data_dir: str) -> None:
    """role.get 應回 body 全文。"""
    _run_sidecar([
        '{"id":"w","method":"role.write","params":'
        '{"name":"x","body":"hello custom"}}',
    ], data_dir)
    frames = _run_sidecar([
        '{"id":"g","method":"role.get","params":{"name":"x"}}',
    ], data_dir)
    g = next(f for f in frames if f.get("id") == "g")
    assert g["event"] == "role"
    assert "hello custom" in g["data"]["body"]


def test_role_get_bundled(data_dir: str) -> None:
    """Bundled role 也可 .get 讀 body。"""
    frames = _run_sidecar([
        '{"id":"g","method":"role.get","params":{"name":"researcher"}}',
    ], data_dir)
    g = next(f for f in frames if f.get("id") == "g")
    assert g["event"] == "role"
    assert g["data"]["source"] == "bundled"
    assert g["data"]["editable"] is False


def test_role_get_not_found(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"g","method":"role.get","params":{"name":"ghost"}}',
    ], data_dir)
    g = next(f for f in frames if f.get("id") == "g")
    assert g["event"] == "error"
    assert g["data"]["code"] == "NOT_FOUND"


def test_role_write_user_overrides_bundled(data_dir: str) -> None:
    """寫同名 user role 應 override bundled 在 list 內。"""
    _run_sidecar([
        '{"id":"w","method":"role.write","params":'
        '{"name":"coder","body":"my coder","description":"customized coder"}}',
    ], data_dir)
    frames = _run_sidecar([
        '{"id":"l","method":"role.list"}',
    ], data_dir)
    listed = next(f for f in frames if f.get("id") == "l")
    by_name = {r["name"]: r for r in listed["data"]["roles"]}
    # 同名 → user 覆蓋,只有 1 個 entry
    assert by_name["coder"]["source"] == "user"
    assert by_name["coder"]["description"] == "customized coder"
    # 其他 bundled 還在
    assert by_name["researcher"]["source"] == "bundled"


def test_role_delete_user_role(data_dir: str) -> None:
    _run_sidecar([
        '{"id":"w","method":"role.write","params":'
        '{"name":"to-delete","body":"x"}}',
    ], data_dir)
    frames_d = _run_sidecar([
        '{"id":"d","method":"role.delete","params":{"filename":"to-delete"}}',
    ], data_dir)
    d = next(f for f in frames_d if f.get("id") == "d")
    assert d["event"] == "role_deleted"
    frames_l = _run_sidecar([
        '{"id":"l","method":"role.list"}',
    ], data_dir)
    listed = next(f for f in frames_l if f.get("id") == "l")
    names = {r["name"] for r in listed["data"]["roles"]}
    assert "to-delete" not in names


def test_role_delete_bundled_rejected(data_dir: str) -> None:
    """刪 bundled role 失敗(只有 user role 可刪)。"""
    frames = _run_sidecar([
        '{"id":"d","method":"role.delete","params":{"filename":"researcher"}}',
    ], data_dir)
    d = next(f for f in frames if f.get("id") == "d")
    assert d["event"] == "error"
    assert d["data"]["code"] == "NOT_FOUND"


def test_role_write_bad_params(data_dir: str) -> None:
    """缺 name → BAD_PARAMS。"""
    frames = _run_sidecar([
        '{"id":"w","method":"role.write","params":{"body":"x"}}',
    ], data_dir)
    w = next(f for f in frames if f.get("id") == "w")
    assert w["event"] == "error"
    assert w["data"]["code"] == "BAD_PARAMS"
