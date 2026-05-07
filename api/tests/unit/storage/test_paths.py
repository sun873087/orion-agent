"""storage/paths.py。"""

from __future__ import annotations

from uuid import uuid4

from orion_agent.storage.paths import default_session_root, session_paths


def test_default_root_uses_env(monkeypatch) -> None:  # noqa: ANN001
    monkeypatch.setenv("ORION_SESSIONS_DIR", "/tmp/test-orion")
    assert str(default_session_root()) == "/tmp/test-orion"


def test_session_paths_layout() -> None:
    sid = uuid4()
    sp = session_paths(sid)
    assert str(sid) in str(sp.root)
    assert sp.transcript == sp.root / "transcript.jsonl"
    assert sp.tool_results_dir == sp.root / "tool-results"
    assert sp.file_history_dir == sp.root / "file-history"
    assert sp.tool_result_path("abc") == sp.root / "tool-results" / "abc.txt"


def test_ensure_dirs_creates_all() -> None:
    sid = uuid4()
    sp = session_paths(sid)
    sp.ensure_dirs()
    assert sp.root.is_dir()
    assert sp.tool_results_dir.is_dir()
    assert sp.file_history_dir.is_dir()
    # idempotent
    sp.ensure_dirs()
