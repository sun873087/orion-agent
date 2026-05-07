"""telemetry.otel — setup_telemetry no-op when no endpoint;metrics 都建立 OK。"""

from __future__ import annotations

import pytest

from orion_agent.telemetry import otel


def test_setup_no_endpoint_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    assert otel.setup_telemetry(force=True) is False


def test_setup_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    otel.setup_telemetry(force=True)
    # 再呼一次,沒有 endpoint 仍 False(no-op)
    assert otel.setup_telemetry() is False


def test_metrics_handles_available() -> None:
    # 即使 no-op tracer,metric handle 都該回非 None 物件,record/add 不該炸
    otel.turn_duration().record(123.0, {"session_id": "s1"})
    otel.tool_duration().record(45.0, {"tool.name": "Bash"})
    otel.api_latency().record(200.0, {"llm.model": "x"})
    otel.token_input().add(10, {"session_id": "s1"})
    otel.token_output().add(5, {"session_id": "s1"})
    otel.cache_read().add(2, {"session_id": "s1"})
    otel.cache_creation().add(3, {"session_id": "s1"})
    otel.tool_errors().add(1, {"tool.name": "Bash"})


def test_tracer_returns_span_in_noop_mode() -> None:
    span = otel.tracer.start_span("test.span")
    span.set_attribute("foo", "bar")
    span.end()
