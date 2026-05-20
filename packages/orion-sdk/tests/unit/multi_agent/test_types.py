"""Multi-agent types。"""

from __future__ import annotations

from uuid import UUID

import pytest

from orion_sdk.multi_agent.types import (
    PeerMessage,
    TaskAssignment,
    WorkerReport,
)


def test_task_assignment_default_id_unique() -> None:
    a = TaskAssignment(description="x")
    b = TaskAssignment(description="y")
    assert isinstance(a.task_id, UUID)
    assert a.task_id != b.task_id


def test_task_assignment_extra_forbid() -> None:
    with pytest.raises(Exception): # noqa: B017 — pydantic ValidationError
        TaskAssignment(description="x", what="?") # type: ignore[call-arg]


def test_worker_report_completed() -> None:
    a = TaskAssignment(description="x")
    r = WorkerReport(
        task_id=a.task_id,
        worker_id="w1",
        status="completed",
        final_text="done",
    )
    assert r.status == "completed"
    assert r.error is None


def test_worker_report_failed_keeps_error() -> None:
    a = TaskAssignment(description="x")
    r = WorkerReport(
        task_id=a.task_id,
        worker_id="w1",
        status="failed",
        error="boom",
    )
    assert r.error == "boom"


def test_peer_message_default_broadcast() -> None:
    m = PeerMessage(from_agent="a", content="hi")
    assert m.to_agent is None
    assert m.from_agent == "a"
    assert isinstance(m.message_id, UUID)


def test_peer_message_unicast() -> None:
    m = PeerMessage(from_agent="a", to_agent="b", content="hi")
    assert m.to_agent == "b"
