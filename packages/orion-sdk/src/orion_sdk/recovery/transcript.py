"""Conversation recovery — Phase 13。對應 TS `src/utils/conversationRecovery.ts`。

修復兩類 corrupt:
1. **JSONL 半行**:`load_transcript_safe(path)` 跳過 `JSONDecodeError`,計數寫進 report
2. **Orphan tool_use**:Phase 2 `storage/resume.py:validate_and_repair_messages` 已實作 —
   本檔的 `load_session_with_recovery` 把那邊的 warnings 收進 RecoveryReport

**閾值守門**(對應 spec § 8 踩雷 #2):corrupt 行 > 有效行 × 0.1 → raise
`SeverelyCorruptedError`,避免靜靜回空對話讓 user 困惑。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID

import structlog

from orion_sdk.storage.paths import session_paths
from orion_sdk.storage.resume import SessionSnapshot, load_session

log = structlog.get_logger()


_SEVERE_CORRUPT_RATIO = 0.1
"""corrupt_lines / valid_lines 超過此比例,視為「整個 transcript 壞掉」並 raise。"""


class SeverelyCorruptedError(Exception):
    """transcript 大量損壞 — caller 應自行處置(例:回報 user / 拒絕 resume)。"""


@dataclass
class RecoveryReport:
    """Recovery 統計。給 caller 寫 log / 回 user。"""

    total_lines: int = 0
    """transcript 總共有幾行(含空行 / 損壞行)。"""

    valid_records: int = 0
    """成功 parse 為 JSON dict 的筆數。"""

    skipped_corrupt_lines: int = 0
    """parse 失敗的行數(JSONDecodeError / 非 dict)。"""

    orphan_tool_use_warnings: list[str] = field(default_factory=list)
    """Phase 2 validate_and_repair_messages 報的 dangling tool_use 訊息。"""

    fix_actions: list[str] = field(default_factory=list)
    """人類可讀的修補摘要(寫進 log / 顯示給 user)。"""

    @property
    def is_severely_corrupted(self) -> bool:
        if self.valid_records == 0:
            return self.skipped_corrupt_lines > 0
        return (
            self.skipped_corrupt_lines / max(self.valid_records, 1)
        ) > _SEVERE_CORRUPT_RATIO


def load_transcript_safe(
    path: Path,
) -> tuple[list[dict[str, Any]], RecoveryReport]:
    """讀整份 JSONL,跳過爛行,寫進 RecoveryReport。

    跟 `storage/session.py:iter_records_sync` 行為一致(都 silently skip),
    但這版**回 RecoveryReport 統計**,讓 caller 可以決定要不要 raise。
    """
    report = RecoveryReport()
    records: list[dict[str, Any]] = []

    if not path.exists():
        return records, report

    try:
        text = path.read_text(encoding="utf-8")
    except OSError as e:
        log.warning("transcript_read_failed", path=str(path), error=str(e))
        return records, report

    for line_no, line in enumerate(text.splitlines(), start=1):
        report.total_lines += 1
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except json.JSONDecodeError as e:
            report.skipped_corrupt_lines += 1
            report.fix_actions.append(
                f"skipped corrupt line {line_no}: {e.msg}",
            )
            log.warning(
                "transcript_corrupt_line",
                path=str(path),
                line_no=line_no,
                error=str(e),
            )
            continue
        if not isinstance(obj, dict):
            report.skipped_corrupt_lines += 1
            report.fix_actions.append(
                f"skipped non-dict line {line_no}: {type(obj).__name__}",
            )
            continue
        records.append(obj)
        report.valid_records += 1

    return records, report


def load_session_with_recovery(
    session_id: UUID,
    *,
    raise_on_severe: bool = False,
) -> tuple[SessionSnapshot, RecoveryReport]:
    """完整 recovery flow(整合 Phase 2 + Phase 13)。

    Args:
        session_id: 要 resume 的 session ID。
        raise_on_severe: True → corrupt 比例超過閾值就 raise SeverelyCorruptedError。
            False(預設) → 仍把 corrupt 細節寫進 report,caller 自己看。

    Returns:
        (SessionSnapshot, RecoveryReport)。
        SessionSnapshot 已套用過 Phase 2 的 dangling tool_use 修補。
    """
    sp = session_paths(session_id)

    # 用 load_transcript_safe 取得 corrupt 統計(Phase 13 新增)
    _records, report = load_transcript_safe(sp.transcript)

    # 然後走 Phase 2 既有 load_session 拿完整 SessionSnapshot
    # (內部用 iter_records_sync — 會 silently skip 同樣的 corrupt 行,結果一致)
    snapshot = load_session(session_id)

    # Phase 2 的 dangling tool_use warnings 收進 report
    report.orphan_tool_use_warnings = list(snapshot.warnings)
    if snapshot.warnings:
        report.fix_actions.extend(snapshot.warnings)

    log.info(
        "recovery_complete",
        session_id=str(session_id),
        total_lines=report.total_lines,
        valid_records=report.valid_records,
        skipped=report.skipped_corrupt_lines,
        orphan_warnings=len(report.orphan_tool_use_warnings),
    )

    if raise_on_severe and report.is_severely_corrupted:
        raise SeverelyCorruptedError(
            f"transcript {sp.transcript} severely corrupted: "
            f"{report.skipped_corrupt_lines} skipped vs "
            f"{report.valid_records} valid (>10%)"
        )

    return snapshot, report


__all__ = [
    "RecoveryReport",
    "SeverelyCorruptedError",
    "load_session_with_recovery",
    "load_transcript_safe",
]
