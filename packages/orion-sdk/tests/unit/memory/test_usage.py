"""Tests for orion_sdk.memory.usage (Layer 3)。"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from orion_sdk.memory.usage import (
    _debouncer,
    compute_usage_score,
    events_path,
    gc_old_events,
    get_usage_stats,
    iter_events,
    record_event,
    record_ranker_hit,
)


@pytest.fixture(autouse=True)
def reset_debouncer():
    _debouncer.reset()
    yield
    _debouncer.reset()


def test_record_event_appends_jsonl(tmp_path: Path) -> None:
    record_event(tmp_path, event_type="ranker_hit", memory_filename="foo.md")
    record_event(tmp_path, event_type="ranker_hit", memory_filename="bar.md")

    lines = events_path(tmp_path).read_text().strip().split("\n")
    assert len(lines) == 2
    assert json.loads(lines[0])["memory"] == "foo.md"
    assert json.loads(lines[1])["memory"] == "bar.md"


def test_record_event_handles_unwritable_dir(tmp_path: Path) -> None:
    # 用一個不存在的 nested path,record_event 應 mkdir + 寫成功
    deep = tmp_path / "x" / "y" / "z"
    record_event(deep, event_type="ranker_hit", memory_filename="a.md")
    assert events_path(deep).exists()


def test_iter_events_skips_malformed_lines(tmp_path: Path) -> None:
    events_path(tmp_path).write_text(
        '{"ts": "2026-01-01T00:00:00+00:00", "type": "ranker_hit", "memory": "ok.md"}\n'
        "not valid json\n"
        '{"ts": "2026-01-02T00:00:00+00:00", "type": "ranker_hit", "memory": "ok2.md"}\n'
    )
    events = list(iter_events(tmp_path))
    assert len(events) == 2
    assert [e["memory"] for e in events] == ["ok.md", "ok2.md"]


def test_compute_usage_score_decay(tmp_path: Path) -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    # 三筆 hit:今天、14 天前(half-life)、56 天前(4 half-lives)
    for offset_days in (0, 14, 56):
        ts = (now - timedelta(days=offset_days)).isoformat()
        with events_path(tmp_path).open("a") as f:
            f.write(json.dumps({"ts": ts, "type": "ranker_hit", "memory": "x.md"}) + "\n")

    score = compute_usage_score("x.md", tmp_path, now=now, half_life_days=14.0)
    # 1.0 (today) + 0.5 (14d) + 0.5^4 (56d) = 1.5625
    assert 1.5 < score < 1.65


def test_compute_usage_score_ignores_other_memories(tmp_path: Path) -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    with events_path(tmp_path).open("w") as f:
        f.write(json.dumps({"ts": now.isoformat(), "type": "ranker_hit", "memory": "x.md"}) + "\n")
        f.write(json.dumps({"ts": now.isoformat(), "type": "ranker_hit", "memory": "y.md"}) + "\n")

    assert compute_usage_score("x.md", tmp_path, now=now) == pytest.approx(1.0)
    assert compute_usage_score("y.md", tmp_path, now=now) == pytest.approx(1.0)
    assert compute_usage_score("z.md", tmp_path, now=now) == 0.0


def test_compute_usage_score_ignores_non_hit_events(tmp_path: Path) -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    with events_path(tmp_path).open("w") as f:
        f.write(json.dumps({"ts": now.isoformat(), "type": "write", "memory": "x.md"}) + "\n")

    assert compute_usage_score("x.md", tmp_path, now=now) == 0.0


def test_get_usage_stats(tmp_path: Path) -> None:
    now = datetime.now(timezone.utc)
    for offset_days in (1, 5, 60):
        with events_path(tmp_path).open("a") as f:
            f.write(json.dumps({
                "ts": (now - timedelta(days=offset_days)).isoformat(),
                "type": "ranker_hit",
                "memory": "z.md",
            }) + "\n")

    stats = get_usage_stats("z.md", tmp_path)
    assert stats["hits_30d"] == 2 # 1d, 5d
    assert stats["hits_90d"] == 3 # 1d, 5d, 60d
    assert stats["last_hit"] is not None


def test_gc_old_events_moves_to_archive(tmp_path: Path) -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    old = (now - timedelta(days=100)).isoformat()
    fresh = (now - timedelta(days=10)).isoformat()
    events_path(tmp_path).write_text(
        json.dumps({"ts": old, "type": "ranker_hit", "memory": "old.md"}) + "\n"
        + json.dumps({"ts": fresh, "type": "ranker_hit", "memory": "fresh.md"}) + "\n"
    )

    archived = gc_old_events(tmp_path, now=now)
    assert archived == 1

    # _events.jsonl 留下 fresh
    remaining = list(iter_events(tmp_path))
    assert len(remaining) == 1
    assert remaining[0]["memory"] == "fresh.md"

    # archive 內有 old
    archive = list(iter_events(tmp_path, include_archive=True))
    assert any(e["memory"] == "old.md" for e in archive)


def test_gc_idempotent(tmp_path: Path) -> None:
    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    events_path(tmp_path).write_text(
        json.dumps({"ts": (now - timedelta(days=10)).isoformat(),
                    "type": "ranker_hit", "memory": "x.md"}) + "\n"
    )
    assert gc_old_events(tmp_path, now=now) == 0 # 沒老的
    assert gc_old_events(tmp_path, now=now) == 0 # 再跑一次也 0


def test_record_ranker_hit_debounces(tmp_path: Path) -> None:
    # 連續呼叫同 memory,只應寫一筆(debounce 內)
    record_ranker_hit(tmp_path, "x.md")
    record_ranker_hit(tmp_path, "x.md")
    record_ranker_hit(tmp_path, "x.md")

    events = list(iter_events(tmp_path))
    assert len(events) == 1


def test_record_ranker_hit_different_memories_not_debounced(tmp_path: Path) -> None:
    record_ranker_hit(tmp_path, "a.md")
    record_ranker_hit(tmp_path, "b.md")
    record_ranker_hit(tmp_path, "c.md")

    events = list(iter_events(tmp_path))
    assert len(events) == 3
