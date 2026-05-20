"""ConversationRecovery — corrupt JSONL + orphan tool_use。"""

from __future__ import annotations

import json
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from orion_sdk.recovery.transcript import (
    SeverelyCorruptedError,
    load_session_with_recovery,
    load_transcript_safe,
)
from orion_sdk.storage.paths import session_paths


def _write_jsonl(path: Path, lines: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")


def test_load_transcript_safe_skips_corrupt(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    _write_jsonl(f, [
        json.dumps({"kind": "message", "ok": True}),
        "this is not json",
        "",
        json.dumps({"kind": "message", "ok": True}),
    ])
    records, report = load_transcript_safe(f)
    assert len(records) == 2
    assert report.valid_records == 2
    assert report.skipped_corrupt_lines == 1


def test_load_transcript_safe_no_file(tmp_path: Path) -> None:
    f = tmp_path / "missing.jsonl"
    records, report = load_transcript_safe(f)
    assert records == []
    assert report.total_lines == 0


def test_load_transcript_safe_skips_non_dict(tmp_path: Path) -> None:
    f = tmp_path / "t.jsonl"
    _write_jsonl(f, [
        json.dumps({"kind": "x"}),
        json.dumps([1, 2, 3]),
        json.dumps("a string"),
    ])
    records, report = load_transcript_safe(f)
    assert len(records) == 1
    assert report.skipped_corrupt_lines == 2


def test_severely_corrupted_property() -> None:
    """corrupt_lines / valid > 10% → is_severely_corrupted=True。"""
    f = Path("/dev/null") # 不會被讀
    _ = load_transcript_safe(f) # warm path
    from orion_sdk.recovery.transcript import RecoveryReport
    r = RecoveryReport(valid_records=10, skipped_corrupt_lines=2)
    assert r.is_severely_corrupted

    r2 = RecoveryReport(valid_records=100, skipped_corrupt_lines=5)
    assert not r2.is_severely_corrupted


def _make_session(session_id: UUID, lines: list[str]) -> Path:
    sp = session_paths(session_id)
    sp.ensure_dirs()
    sp.transcript.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return sp.transcript


def test_load_session_with_recovery_corrupt_transcript(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """corrupt 行 + 有效 record 都正確處理。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    sid = uuid4()
    _make_session(sid, [
        json.dumps({
            "kind": "session-meta",
            "provider": "anthropic",
            "model": "x",
            "system_prompt": "",
        }),
        "{ corrupt half-line",
        json.dumps({
            "kind": "message",
            "message": {"role": "user", "content": "hi"},
        }),
    ])
    snapshot, report = load_session_with_recovery(sid)
    assert snapshot.provider == "anthropic"
    assert len(snapshot.messages) == 1
    assert report.skipped_corrupt_lines == 1
    assert report.valid_records == 2


def test_load_session_with_recovery_orphan_tool_use(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    """assistant 訊息有 tool_use 但沒對應 result → 收進 orphan_tool_use_warnings。"""
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    sid = uuid4()
    assistant_msg = {
        "role": "assistant",
        "content": [
            {"type": "text", "text": "calling tool"},
            {
                "type": "tool_use",
                "id": "tu1",
                "name": "Bash",
                "input": {"command": "ls"},
            },
        ],
    }
    _make_session(sid, [
        json.dumps({"kind": "session-meta", "provider": "anthropic", "model": "x"}),
        json.dumps({"kind": "message", "message": {"role": "user", "content": "go"}}),
        json.dumps({"kind": "message", "message": assistant_msg}),
        # 沒有對應的 tool_result → orphan
    ])
    snapshot, report = load_session_with_recovery(sid)
    assert len(report.orphan_tool_use_warnings) >= 1
    # validate_and_repair_messages 已注 synthetic result(既有)
    last = snapshot.messages[-1]
    assert last.role == "user"
    assert isinstance(last.content, list)
    has_synthetic = any(
        getattr(b, "tool_use_id", None) == "tu1" for b in last.content
    )
    assert has_synthetic


def test_raise_on_severe(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ORION_SESSIONS_DIR", str(tmp_path))
    sid = uuid4()
    # 1 valid + 5 corrupt → ratio > 10%
    _make_session(sid, [
        json.dumps({"kind": "message", "message": {"role": "user", "content": "x"}}),
        "broken1", "broken2", "broken3", "broken4", "broken5",
    ])
    with pytest.raises(SeverelyCorruptedError):
        load_session_with_recovery(sid, raise_on_severe=True)
