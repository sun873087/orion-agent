"""Phase 31-D:Cowork SQLite persistence cross-restart 驗證。

不需要真 LLM:用 sub-process spawn sidecar → 注 stdin / 讀 stdout 驗證
list / delete 跨 process 都對。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest


def _run_sidecar(input_lines: list[str], data_dir: str, timeout: float = 15.0) -> list[dict]:
    """Spawn sidecar 一次,送 input,等 EOF/結束,回 parsed frames。"""
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
    with tempfile.TemporaryDirectory(prefix="cowork-e2e-") as d:
        yield d


def test_conversation_persists_across_process_restart(data_dir: str) -> None:
    """Process A 建對話 → 結束 → Process B 列出該對話。"""
    # A:create
    frames_a = _run_sidecar([
        '{"id":"a","method":"conversation.create","params":{"provider":"anthropic","model":"claude-haiku-4-5"}}',
    ], data_dir)
    created = next(f for f in frames_a if f.get("id") == "a")
    assert created["event"] == "conversation_created"
    sid = created["data"]["session_id"]
    assert sid

    # B:fresh process,list
    frames_b = _run_sidecar([
        '{"id":"b","method":"conversation.list"}',
    ], data_dir)
    listed = next(f for f in frames_b if f.get("id") == "b")
    assert listed["event"] == "conversation_list"
    sessions = listed["data"]["sessions"]
    assert any(s["session_id"] == sid for s in sessions)
    assert any(s["provider"] == "anthropic" for s in sessions)


def test_conversation_delete_persists(data_dir: str) -> None:
    # Create 2 sessions in process A
    frames_a = _run_sidecar([
        '{"id":"1","method":"conversation.create","params":{}}',
        '{"id":"2","method":"conversation.create","params":{}}',
    ], data_dir)
    sid1 = next(f for f in frames_a if f.get("id") == "1")["data"]["session_id"]
    sid2 = next(f for f in frames_a if f.get("id") == "2")["data"]["session_id"]

    # Process B:delete sid1
    _run_sidecar([
        f'{{"id":"d","method":"conversation.delete","params":{{"session_id":"{sid1}"}}}}',
    ], data_dir)

    # Process C:list — should only have sid2
    frames_c = _run_sidecar([
        '{"id":"l","method":"conversation.list"}',
    ], data_dir)
    listed = next(f for f in frames_c if f.get("id") == "l")
    sessions = listed["data"]["sessions"]
    ids = {s["session_id"] for s in sessions}
    assert sid2 in ids
    assert sid1 not in ids


def test_db_file_created_in_data_dir(data_dir: str) -> None:
    _run_sidecar(['{"id":"1","method":"ping"}'], data_dir)
    # Ping doesn't touch DB,但其他 method 會;觸發 list 強制 init
    _run_sidecar(['{"id":"2","method":"conversation.list"}'], data_dir)
    assert Path(data_dir, "sessions.db").exists()
