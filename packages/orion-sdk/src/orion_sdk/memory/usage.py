"""Memory Layer 3 — 使用率追蹤(Phase 31-G)。

Append-only event log + exponential decay score。

設計:
- 每筆 ranker_hit / write event 寫進 memory 目錄下 `_events.jsonl`
- score 用 exponential decay:近期 hit 權重高,90 天前的 hit 權重低於 1%
- Layer 3 解「殭屍 memory」— 沒過期、沒重複、但沒人在用

整合進 ranker:`relevance.rank_memories` 在 heuristic 路徑加上 usage_weight,
低 score memory 即使語意 match 也排後面。

預設 `ORION_MEMORY_USAGE_WEIGHT=0`(關閉,向後相容),手動 opt-in。
"""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterable
from contextlib import suppress
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import structlog

log = structlog.get_logger(__name__)

_EVENTS_FILENAME = "_events.jsonl"
_DEFAULT_HALF_LIFE_DAYS = 14.0  # score 半衰期:14 天前的 hit 權重 = 0.5
_KEEP_EVENTS_DAYS = 90  # > 90 天 events 移到 _events.archive.jsonl


def events_path(memory_dir: Path) -> Path:
    return memory_dir / _EVENTS_FILENAME


def archive_path(memory_dir: Path) -> Path:
    return memory_dir / "_events.archive.jsonl"


def record_event(
    memory_dir: Path,
    *,
    event_type: str,
    memory_filename: str,
    extra: dict[str, Any] | None = None,
) -> None:
    """寫一筆 event。失敗 silently log(usage tracking 不該擋 agent run)。

    event_type 慣用:`ranker_hit`、`write`、`open`(future:UI 點開)
    """
    try:
        memory_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "memory": memory_filename,
            **(extra or {}),
        }
        with events_path(memory_dir).open("a", encoding="utf-8") as f:
            f.write(json.dumps(payload, ensure_ascii=False) + "\n")
    except OSError as e:
        log.warning("memory.usage.record_failed", error=str(e), memory=memory_filename)


def _parse_event(line: str) -> dict[str, Any] | None:
    try:
        return json.loads(line)
    except json.JSONDecodeError:
        return None


def iter_events(memory_dir: Path, *, include_archive: bool = False) -> Iterable[dict[str, Any]]:
    """Iter event records(最新在後)。壞行靜默跳過。"""
    files = [events_path(memory_dir)]
    if include_archive:
        files.insert(0, archive_path(memory_dir))
    for path in files:
        if not path.exists():
            continue
        with path.open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                ev = _parse_event(line)
                if ev is not None:
                    yield ev


def _parse_ts(ts_str: str) -> datetime | None:
    with suppress(ValueError):
        return datetime.fromisoformat(ts_str)
    return None


def compute_usage_score(
    memory_filename: str,
    memory_dir: Path,
    *,
    now: datetime | None = None,
    half_life_days: float = _DEFAULT_HALF_LIFE_DAYS,
) -> float:
    """Exponential decay score。

    score = Σ 0.5 ^ (age_days / half_life_days),只計 ranker_hit events。
    新 memory 沒 hit → score = 0(不會被排前)。
    """
    now = now or datetime.now(timezone.utc)
    score = 0.0
    for ev in iter_events(memory_dir):
        if ev.get("memory") != memory_filename or ev.get("type") != "ranker_hit":
            continue
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        age_days = (now - ts).total_seconds() / 86400.0
        if age_days < 0:
            age_days = 0
        score += 0.5 ** (age_days / half_life_days)
    return score


def get_usage_stats(memory_filename: str, memory_dir: Path) -> dict[str, Any]:
    """Return per-memory stats:hits_30d、hits_90d、last_hit timestamp。"""
    now = datetime.now(timezone.utc)
    hits_30d = 0
    hits_90d = 0
    last_hit_ts: datetime | None = None
    for ev in iter_events(memory_dir):
        if ev.get("memory") != memory_filename or ev.get("type") != "ranker_hit":
            continue
        ts = _parse_ts(ev.get("ts", ""))
        if ts is None:
            continue
        age_days = (now - ts).total_seconds() / 86400.0
        if age_days <= 30:
            hits_30d += 1
        if age_days <= 90:
            hits_90d += 1
        if last_hit_ts is None or ts > last_hit_ts:
            last_hit_ts = ts
    return {
        "hits_30d": hits_30d,
        "hits_90d": hits_90d,
        "last_hit": last_hit_ts.isoformat() if last_hit_ts else None,
    }


def gc_old_events(memory_dir: Path, *, now: datetime | None = None) -> int:
    """把 > _KEEP_EVENTS_DAYS 天的 events 從 _events.jsonl 搬到 _events.archive.jsonl。

    Return:搬走的筆數。

    Safe to call repeatedly;結構是 read events.jsonl → split → rewrite events.jsonl
    跟 append archive。失敗保持原檔不動。
    """
    now = now or datetime.now(timezone.utc)
    src = events_path(memory_dir)
    if not src.exists():
        return 0
    keep: list[str] = []
    archived: list[str] = []
    with src.open(encoding="utf-8") as f:
        for line in f:
            line_stripped = line.strip()
            if not line_stripped:
                continue
            ev = _parse_event(line_stripped)
            if ev is None:
                # 壞行也保留(避免靜默丟資料)
                keep.append(line)
                continue
            ts = _parse_ts(ev.get("ts", ""))
            if ts is None:
                keep.append(line)
                continue
            age_days = (now - ts).total_seconds() / 86400.0
            if age_days > _KEEP_EVENTS_DAYS:
                archived.append(line)
            else:
                keep.append(line)
    if not archived:
        return 0
    # atomic-ish rewrite:寫新 file → rename
    new = src.with_suffix(".tmp")
    new.write_text("".join(keep), encoding="utf-8")
    with archive_path(memory_dir).open("a", encoding="utf-8") as f:
        f.writelines(archived)
    new.replace(src)
    return len(archived)


def usage_weight() -> float:
    """讀環境變數,預設 0(關閉)。範圍 [0, 1]。"""
    raw = os.environ.get("ORION_MEMORY_USAGE_WEIGHT", "0")
    try:
        w = float(raw)
    except ValueError:
        return 0.0
    return max(0.0, min(1.0, w))


def benchmark_window() -> float:
    """ranker_hit event log 寫入頻率上限 — 每 N 秒最多寫一筆同 memory。

    防 ranker 重複 emit 把 events.jsonl 灌爆(同 turn 內 retry / re-rank)。
    """
    raw = os.environ.get("ORION_MEMORY_USAGE_DEBOUNCE_SECONDS", "5")
    try:
        return float(raw)
    except ValueError:
        return 5.0


class _Debouncer:
    """Per-process in-memory debounce — 同 memory N 秒內只寫一次 hit。"""

    def __init__(self) -> None:
        self._last_write: dict[str, float] = {}

    def should_write(self, memory_filename: str) -> bool:
        now_mono = time.monotonic()
        last = self._last_write.get(memory_filename, 0.0)
        if now_mono - last < benchmark_window():
            return False
        self._last_write[memory_filename] = now_mono
        return True

    def reset(self) -> None:
        self._last_write.clear()


_debouncer = _Debouncer()


def record_ranker_hit(memory_dir: Path, memory_filename: str) -> None:
    """寫一筆 ranker_hit event,帶 debounce。"""
    if not _debouncer.should_write(memory_filename):
        return
    record_event(memory_dir, event_type="ranker_hit", memory_filename=memory_filename)
