"""Multi-pane collaboration — RPC + cross-pane query e2e。

走 sub-process spawn sidecar 驗證 RPC 端到端 + AskPaneTool callback
真的能讀到對方 pane 的 transcript。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

import pytest


def _run_sidecar(input_lines: list[str], data_dir: str, timeout: float = 20.0) -> list[dict]:
    env = dict(os.environ)
    env["ORION_COWORK_DATA_DIR"] = data_dir
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
    with tempfile.TemporaryDirectory(prefix="cowork-collab-e2e-") as d:
        yield d


def test_collaboration_create_and_list(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"feature-x"}}',
        '{"id":"l","method":"collaboration.list"}',
    ], data_dir)
    created = next(f for f in frames if f.get("id") == "c")
    assert created["event"] == "collaboration_created"
    coll = created["data"]["collaboration"]
    cid = coll["id"]
    assert coll["name"] == "feature-x"

    listed = next(f for f in frames if f.get("id") == "l")
    assert listed["event"] == "collaboration_list"
    items = listed["data"]["items"]
    assert len(items) == 1
    assert items[0]["collaboration"]["id"] == cid


def test_collaboration_create_with_workspace_and_budget(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create",'
        '"params":{"name":"feature-y","workspace_dir":"/tmp/ws","budget_usd_cap":5}}',
    ], data_dir)
    created = next(f for f in frames if f.get("id") == "c")
    coll = created["data"]["collaboration"]
    assert coll["workspace_dir"] == "/tmp/ws"
    assert coll["budget_usd_cap"] == 5.0


def test_add_pane_and_get(data_dir: str) -> None:
    """建 conversation → 建 collab → add_pane → get 看 panes 出現。

    注意:sidecar RPC dispatch 是 concurrent — add_pane 跟 get 不能在同
    一個 subprocess 連發(會 race)。分多個 subprocess 才能確保 commit 先完成。
    """
    frames = _run_sidecar([
        '{"id":"conv","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
        '{"id":"c","method":"collaboration.create","params":{"name":"team"}}',
    ], data_dir)
    sid = next(f for f in frames if f.get("id") == "conv")["data"]["session_id"]
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]

    frames_add = _run_sidecar([
        f'{{"id":"a","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid}",'
        f'"pane_name":"@coder","pane_role":"coder"}}}}',
    ], data_dir)
    added = next(f for f in frames_add if f.get("id") == "a")
    assert added["event"] == "pane_added"

    frames_get = _run_sidecar([
        f'{{"id":"g","method":"collaboration.get","params":{{"collaboration_id":"{cid}"}}}}',
    ], data_dir)
    got = next(f for f in frames_get if f.get("id") == "g")
    assert got["event"] == "collaboration_get"
    panes = got["data"]["panes"]
    assert len(panes) == 1
    assert panes[0]["pane_name"] == "@coder"
    assert panes[0]["pane_role"] == "coder"
    assert panes[0]["session_id"] == sid


def test_add_pane_conflict_same_name(data_dir: str) -> None:
    """同 collab 兩 pane 不能同名。"""
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"t"}}',
        '{"id":"conv1","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
        '{"id":"conv2","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]
    sid1 = next(f for f in frames if f.get("id") == "conv1")["data"]["session_id"]
    sid2 = next(f for f in frames if f.get("id") == "conv2")["data"]["session_id"]

    frames_a1 = _run_sidecar([
        f'{{"id":"a1","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid1}","pane_name":"@coder"}}}}',
    ], data_dir)
    assert next(f for f in frames_a1 if f.get("id") == "a1")["event"] == "pane_added"
    frames_a2 = _run_sidecar([
        f'{{"id":"a2","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid2}","pane_name":"@coder"}}}}',
    ], data_dir)
    second = next(f for f in frames_a2 if f.get("id") == "a2")
    assert second["event"] == "error"
    assert second["data"]["code"] == "CONFLICT"


def test_remove_pane(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"t"}}',
        '{"id":"conv","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]
    sid = next(f for f in frames if f.get("id") == "conv")["data"]["session_id"]

    _run_sidecar([
        f'{{"id":"a","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid}","pane_name":"@x"}}}}',
    ], data_dir)
    frames_rm = _run_sidecar([
        f'{{"id":"r","method":"collaboration.remove_pane",'
        f'"params":{{"session_id":"{sid}"}}}}',
    ], data_dir)
    rem = next(f for f in frames_rm if f.get("id") == "r")
    assert rem["event"] == "pane_removed"
    assert rem["data"]["collaboration_id"] == cid
    frames_g = _run_sidecar([
        f'{{"id":"g","method":"collaboration.get","params":{{"collaboration_id":"{cid}"}}}}',
    ], data_dir)
    got = next(f for f in frames_g if f.get("id") == "g")
    assert got["data"]["panes"] == []


def test_update_pane_position(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"t"}}',
        '{"id":"conv","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]
    sid = next(f for f in frames if f.get("id") == "conv")["data"]["session_id"]

    _run_sidecar([
        f'{{"id":"a","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid}","pane_name":"@x"}}}}',
    ], data_dir)
    frames_u = _run_sidecar([
        f'{{"id":"u","method":"collaboration.update_pane_position",'
        f'"params":{{"session_id":"{sid}","pane_position":{{"w":80,"h":50,"minimized":false}}}}}}',
    ], data_dir)
    u = next(f for f in frames_u if f.get("id") == "u")
    assert u["event"] == "pane_position_updated"
    assert u["data"]["ok"] is True
    frames_g = _run_sidecar([
        f'{{"id":"g","method":"collaboration.get","params":{{"collaboration_id":"{cid}"}}}}',
    ], data_dir)
    got = next(f for f in frames_g if f.get("id") == "g")
    panes = got["data"]["panes"]
    assert panes[0]["pane_position"] == {"w": 80, "h": 50, "minimized": False}


def test_delete_collaboration_with_delete_sessions(data_dir: str) -> None:
    """delete_sessions=True → 成員 session 也跟著刪。"""
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"t"}}',
        '{"id":"conv","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]
    sid = next(f for f in frames if f.get("id") == "conv")["data"]["session_id"]

    _run_sidecar([
        f'{{"id":"a","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid}","pane_name":"@x"}}}}',
    ], data_dir)
    frames_del = _run_sidecar([
        f'{{"id":"d","method":"collaboration.delete",'
        f'"params":{{"collaboration_id":"{cid}","delete_sessions":true}}}}',
    ], data_dir)
    d = next(f for f in frames_del if f.get("id") == "d")
    assert d["event"] == "collaboration_deleted"
    assert d["data"]["deleted_session_count"] == 1
    frames_check = _run_sidecar([
        '{"id":"cl","method":"conversation.list"}',
    ], data_dir)
    cl = next(f for f in frames_check if f.get("id") == "cl")
    # Session 也消失,不會留在 conversation.list
    assert not any(s["session_id"] == sid for s in cl["data"]["sessions"])


def test_delete_collaboration_releases_panes(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"t"}}',
        '{"id":"conv","method":"conversation.create",'
        '"params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]
    sid = next(f for f in frames if f.get("id") == "conv")["data"]["session_id"]

    _run_sidecar([
        f'{{"id":"a","method":"collaboration.add_pane",'
        f'"params":{{"collaboration_id":"{cid}","session_id":"{sid}","pane_name":"@x"}}}}',
    ], data_dir)
    frames_del = _run_sidecar([
        f'{{"id":"d","method":"collaboration.delete","params":{{"collaboration_id":"{cid}"}}}}',
    ], data_dir)
    d = next(f for f in frames_del if f.get("id") == "d")
    assert d["event"] == "collaboration_deleted"
    frames_check = _run_sidecar([
        '{"id":"cl","method":"conversation.list"}',
        '{"id":"cll","method":"collaboration.list"}',
    ], data_dir)
    cl = next(f for f in frames_check if f.get("id") == "cl")
    assert any(s["session_id"] == sid for s in cl["data"]["sessions"])
    cll = next(f for f in frames_check if f.get("id") == "cll")
    assert cll["data"]["items"] == []


def test_cost_summary_empty(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"c","method":"collaboration.create","params":{"name":"t"}}',
    ], data_dir)
    cid = next(f for f in frames if f.get("id") == "c")["data"]["collaboration"]["id"]
    frames2 = _run_sidecar([
        f'{{"id":"s","method":"collaboration.cost_summary","params":{{"collaboration_id":"{cid}"}}}}',
    ], data_dir)
    s = next(f for f in frames2 if f.get("id") == "s")
    assert s["event"] == "collaboration_cost_summary"
    assert s["data"]["total_panes"] == 0
    assert s["data"]["total_cost_usd"] == 0.0


def test_get_collaboration_not_found(data_dir: str) -> None:
    frames = _run_sidecar([
        '{"id":"g","method":"collaboration.get","params":{"collaboration_id":"ghost-id"}}',
    ], data_dir)
    g = next(f for f in frames if f.get("id") == "g")
    assert g["event"] == "error"
    assert g["data"]["code"] == "NOT_FOUND"


def test_add_pane_bad_params(data_dir: str) -> None:
    """missing pane_name → BAD_PARAMS。"""
    frames = _run_sidecar([
        '{"id":"a","method":"collaboration.add_pane",'
        '"params":{"collaboration_id":"x","session_id":"y"}}',
    ], data_dir)
    a = next(f for f in frames if f.get("id") == "a")
    assert a["event"] == "error"
    assert a["data"]["code"] == "BAD_PARAMS"
