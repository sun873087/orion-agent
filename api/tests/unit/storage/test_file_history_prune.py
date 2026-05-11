"""Phase 19:file_history snapshot 上限與 mtime LRU prune。

- 150 個 snapshot → 預設上限 100 後只剩 100
- 留下的是最新(mtime 高)那批
- ORION_FILE_HISTORY_MAX_SNAPSHOTS env 可調整上限
- 0 / 負數 / 非數字 fallback 預設;<=0 給 prune_old_snapshots 視為 no-op
- 未達上限不刪
- dedupe(同 hash 重複 make_snapshot)不觸發 prune
"""

from __future__ import annotations

import re
import time
from pathlib import Path
from uuid import uuid4

import pytest

from orion_agent.storage.file_history import (
    make_snapshot,
    prune_old_snapshots,
)
from orion_agent.storage.paths import session_paths


def _write_n_snapshots(n: int, tmp_path: Path, sid: object) -> None:
    """寫 n 個不同內容的檔並 make_snapshot,各檔 mtime 遞增。"""
    for i in range(n):
        p = tmp_path / f"f{i:04d}.txt"
        p.write_text(f"version {i}", encoding="utf-8")
        make_snapshot(sid, p)  # type: ignore[arg-type]
        # 確保 mtime 嚴格遞增(避免同一秒多檔 mtime tie)
        time.sleep(0.001)


def test_prune_keeps_default_cap(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """150 個 snapshot,預設 100 上限 → 剩 100。"""
    monkeypatch.delenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", raising=False)
    sid = uuid4()
    _write_n_snapshots(150, tmp_path, sid)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 100


def test_prune_drops_oldest_keeps_newest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LRU 砍最舊 → 留的應對應寫進去比較晚的版本內容。"""
    monkeypatch.setenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", "10")
    sid = uuid4()
    _write_n_snapshots(25, tmp_path, sid)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 10

    # 讀內容驗證 — 應保留 version 15..24(最後 10 個寫的)。
    # 用 regex 精準抓 "version N" 末尾,避免 "version 1" substring 匹到 "version 15"。
    versions_kept = set()
    pattern = re.compile(r"version (\d+)\b")
    for s in snaps:
        body = s.read_text(encoding="utf-8")
        # 跳過 header(`# snapshot of /tmp/.../fNNNN.txt`),只看 body 的 `version N`
        body_only = body.split("---SNAPSHOT---\n", 1)[-1]
        m = pattern.search(body_only)
        if m:
            versions_kept.add(int(m.group(1)))
    assert versions_kept == set(range(15, 25)), (
        f"expected versions 15..24, got {sorted(versions_kept)}"
    )


def test_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", "5")
    sid = uuid4()
    _write_n_snapshots(20, tmp_path, sid)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 5


def test_env_invalid_falls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", "not-a-number")
    sid = uuid4()
    _write_n_snapshots(120, tmp_path, sid)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 100  # default


def test_env_zero_disables_prune(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """0 視為「不 prune」— 但 fallback 邏輯目前是「<= 0 走 default 100」,所以
    這個測試實際驗證:0 / 負數會 fallback 預設 100(不會無限累積)。"""
    monkeypatch.setenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", "0")
    sid = uuid4()
    _write_n_snapshots(120, tmp_path, sid)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 100


def test_under_cap_noop(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """未達上限 → 不刪任何 snapshot。"""
    monkeypatch.setenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", "100")
    sid = uuid4()
    _write_n_snapshots(30, tmp_path, sid)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 30


def test_prune_helper_direct(tmp_path: Path) -> None:
    """prune_old_snapshots 直接 call,驗證返回刪除數量。"""
    sid = uuid4()
    _write_n_snapshots(50, tmp_path, sid)
    deleted = prune_old_snapshots(sid, max_count=10)
    assert deleted == 40

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 10


def test_prune_no_dir_safe(tmp_path: Path) -> None:
    """session 沒寫過任何檔(file-history dir 不存在)→ prune 應該安全回 0。"""
    sid = uuid4()
    deleted = prune_old_snapshots(sid, max_count=10)
    assert deleted == 0


def test_prune_max_count_zero_or_negative(tmp_path: Path) -> None:
    """直接呼叫 prune 給 0 / 負數 → 視為 no-op 不刪檔。"""
    sid = uuid4()
    _write_n_snapshots(30, tmp_path, sid)
    assert prune_old_snapshots(sid, max_count=0) == 0
    assert prune_old_snapshots(sid, max_count=-5) == 0

    sp = session_paths(sid)
    assert len(list(sp.file_history_dir.glob("*.snap"))) == 30


def test_dedupe_does_not_trigger_prune(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """同 hash 重複 make_snapshot → 走 dedupe 早 return,不進 prune(行為 invariant
    保護:dedupe 不能因為 prune 重複刪同 hash 檔案)。

    驗證方式:寫 5 個 unique,重複呼叫同檔的 make_snapshot 100 次,最終仍是 5 個 snap。
    """
    monkeypatch.setenv("ORION_FILE_HISTORY_MAX_SNAPSHOTS", "100")
    sid = uuid4()
    files = []
    for i in range(5):
        p = tmp_path / f"f{i}.txt"
        p.write_text(f"v{i}", encoding="utf-8")
        files.append(p)
        make_snapshot(sid, p)

    # 重複快照同 5 個檔(同 hash → dedupe)
    for _ in range(100):
        for p in files:
            make_snapshot(sid, p)

    sp = session_paths(sid)
    snaps = list(sp.file_history_dir.glob("*.snap"))
    assert len(snaps) == 5
