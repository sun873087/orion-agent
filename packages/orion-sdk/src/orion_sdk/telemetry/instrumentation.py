"""OTel 切點包裝。

3 個 ctx manager:
- `trace_turn(session_id, user_id)` — Conversation.send 入口
- `trace_tool_call(tool_name, tool_use_id, session_id)` — tool_execution.run_one_tool
- `trace_api_call(model, session_id)` — LLMProvider.stream

外加 `record_usage(...)` 把 LLM response.usage 寫進 cost_tracker + OTel counter。

沒設 OTLP endpoint 時 — span 進 no-op tracer,context manager 仍正常 enter/exit。
overhead 接近零。
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from contextlib import asynccontextmanager, contextmanager

from opentelemetry import trace
from opentelemetry.trace import Span

from orion_sdk.telemetry.cost_tracker import get_or_create_tracker
from orion_sdk.telemetry.otel import (
    api_latency,
    cache_creation,
    cache_read,
    token_input,
    token_output,
    tool_duration,
    tool_errors,
    tracer,
    turn_duration,
)


@contextmanager
def trace_turn(
    session_id: str,
    user_id: str | None,
    *,
    turn_index: int | None = None,
) -> Iterator[Span]:
    """整個 user-prompt → terminal 的 turn。"""
    attrs: dict[str, str | int] = {
        "session_id": session_id,
        "user_id": user_id or "anonymous",
    }
    if turn_index is not None:
        attrs["turn.index"] = turn_index
    with tracer.start_as_current_span("orion_agent.turn", attributes=attrs) as span:
        start = time.monotonic()
        try:
            yield span
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            turn_duration().record(duration_ms, {"session_id": session_id})


@contextmanager
def trace_tool_call(
    *,
    tool_name: str,
    tool_use_id: str,
    session_id: str,
) -> Iterator[Span]:
    """單一 tool 執行(對應 tool_execution.run_one_tool)。"""
    with tracer.start_as_current_span(
        "orion_agent.tool",
        attributes={
            "tool.name": tool_name,
            "tool.use_id": tool_use_id,
            "session_id": session_id,
        },
    ) as span:
        start = time.monotonic()
        try:
            yield span
        except Exception as e:
            span.record_exception(e)
            span.set_status(trace.Status(trace.StatusCode.ERROR))
            tool_errors().add(1, {"tool.name": tool_name, "session_id": session_id})
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            tool_duration().record(
                duration_ms,
                {"tool.name": tool_name, "session_id": session_id},
            )


@asynccontextmanager
async def trace_api_call(
    *,
    model: str,
    session_id: str,
    provider: str = "anthropic",
) -> AsyncIterator[Span]:
    """LLM API 呼叫(對應 LLMProvider.stream)。"""
    with tracer.start_as_current_span(
        "orion_chat_api",
        attributes={
            "llm.model": model,
            "llm.provider": provider,
            "session_id": session_id,
        },
    ) as span:
        start = time.monotonic()
        try:
            yield span
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            api_latency().record(
                duration_ms,
                {"llm.model": model, "llm.provider": provider},
            )


def record_usage(
    *,
    session_id: str,
    user_id: str | None,
    model: str,
    input_tokens: int = 0,
    output_tokens: int = 0,
    cache_creation_tokens: int = 0,
    cache_read_tokens: int = 0,
    duration_ms: float = 0.0,
) -> None:
    """把 LLM API response.usage 寫進 cost_tracker + OTel counter。"""
    # cost tracker
    tracker = get_or_create_tracker(session_id, user_id)
    tracker.record(
        model=model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_creation_tokens=cache_creation_tokens,
        cache_read_tokens=cache_read_tokens,
        duration_ms=duration_ms,
    )

    # OTel counters
    attrs = {"llm.model": model, "session_id": session_id}
    if input_tokens:
        token_input().add(int(input_tokens), attrs)
    if output_tokens:
        token_output().add(int(output_tokens), attrs)
    if cache_read_tokens:
        cache_read().add(int(cache_read_tokens), attrs)
    if cache_creation_tokens:
        cache_creation().add(int(cache_creation_tokens), attrs)
