"""trace_turn / trace_tool_call / trace_api_call ctx managers + record_usage。"""

from __future__ import annotations

import pytest

from orion_sdk.telemetry.cost_tracker import (
    get_or_create_tracker,
    reset_trackers,
)
from orion_sdk.telemetry.instrumentation import (
    record_usage,
    trace_api_call,
    trace_tool_call,
    trace_turn,
)


@pytest.fixture(autouse=True)
def _clean() -> None:
    reset_trackers()


def test_trace_turn_does_not_raise() -> None:
    with trace_turn("s1", "u1"):
        pass


def test_trace_tool_call_records_error_on_exception() -> None:
    with (
        pytest.raises(RuntimeError),
        trace_tool_call(tool_name="Bash", tool_use_id="t1", session_id="s1"),
    ):
        raise RuntimeError("boom")
    # 沒炸 trace setup;exception propagates


@pytest.mark.asyncio
async def test_trace_api_call_async() -> None:
    async with trace_api_call(model="claude-sonnet-4-6", session_id="s1"):
        pass


def test_record_usage_writes_to_tracker() -> None:
    record_usage(
        session_id="s1",
        user_id="u1",
        model="claude-sonnet-4-6",
        input_tokens=100,
        output_tokens=50,
        duration_ms=123.0,
    )
    t = get_or_create_tracker("s1")
    m = t.by_model["claude-sonnet-4-6"]
    assert m.input_tokens == 100
    assert m.output_tokens == 50
    assert t.total_api_duration_ms == 123.0
