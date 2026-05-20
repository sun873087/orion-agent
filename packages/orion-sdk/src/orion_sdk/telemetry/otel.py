"""OpenTelemetry setup。

預設 **no-op** — 沒設 `OTEL_EXPORTER_OTLP_ENDPOINT` 不啟 exporter,
trace / metrics 進 default no-op provider(`opentelemetry-api` 內建)。

設了 endpoint(例:`localhost:4317` 給 Jaeger / OTLP Collector)→
建立 `TracerProvider` + OTLP gRPC exporter,自動上報。

Caller 在 app startup(FastAPI lifespan / CLI main)呼一次 `setup_telemetry()`。
之後 `tracer / meter / *_metric` 全域可用。

不啟 exporter 時 instrument 仍跑(span 進 NoOp tracer),零 overhead。
"""

from __future__ import annotations

import logging
import os
from typing import Any

from opentelemetry import metrics, trace
from opentelemetry.metrics import Counter, Histogram, Meter
from opentelemetry.trace import Tracer

logger = logging.getLogger(__name__)


_SERVICE_NAME = "orion-agent"
_SERVICE_VERSION = "0.1.0"


_initialized: bool = False


def setup_telemetry(*, force: bool = False) -> bool:
    """初始化 OTel provider + exporter。重複呼 idempotent(除非 force)。

    Returns:
        True 若有真的接 exporter;False 若 no-op(沒 endpoint / 失敗)。
    """
    global _initialized
    if _initialized and not force:
        return _has_otlp_endpoint()

    endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not endpoint:
        # no-op — trace / metrics API 仍可呼,只是不上報
        _initialized = True
        return False

    try:
        # 延遲 import — 沒設 endpoint 不需 sdk dep load
        from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import (
            OTLPMetricExporter,
        )
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import (
            OTLPSpanExporter,
        )
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        resource = Resource.create(
            {"service.name": _SERVICE_NAME, "service.version": _SERVICE_VERSION},
        )

        tp = TracerProvider(resource=resource)
        tp.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)),
        )
        trace.set_tracer_provider(tp)

        reader = PeriodicExportingMetricReader(
            OTLPMetricExporter(endpoint=endpoint, insecure=True),
            export_interval_millis=10_000,
        )
        mp = MeterProvider(resource=resource, metric_readers=[reader])
        metrics.set_meter_provider(mp)

        _initialized = True
        logger.info("OTel exporter enabled — endpoint=%s", endpoint)
        return True
    except Exception as e: # noqa: BLE001
        logger.warning("OTel exporter setup failed (%s) — falling back to no-op", e)
        _initialized = True
        return False


def _has_otlp_endpoint() -> bool:
    return bool(os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip())


# ─── 全域 tracer / meter ────────────────────────────────────────────────

tracer: Tracer = trace.get_tracer(_SERVICE_NAME)
meter: Meter = metrics.get_meter(_SERVICE_NAME)


# ─── 預先建好的 metrics(常用 — 不重複建)────────────────────────────────


def _build_metrics() -> dict[str, Any]:
    return {
        "turn_duration": meter.create_histogram(
            "orion_agent.turn.duration",
            unit="ms",
            description="End-to-end turn duration",
        ),
        "tool_duration": meter.create_histogram(
            "orion_agent.tool.duration",
            unit="ms",
            description="Single tool call duration",
        ),
        "api_latency": meter.create_histogram(
            "orion_chat_api.latency",
            unit="ms",
            description="LLM API latency",
        ),
        "token_input": meter.create_counter(
            "orion_agent.tokens.input",
            description="Total input tokens",
        ),
        "token_output": meter.create_counter(
            "orion_agent.tokens.output",
            description="Total output tokens",
        ),
        "cache_read": meter.create_counter(
            "orion_agent.tokens.cache_read",
            description="Cache-hit input tokens",
        ),
        "cache_creation": meter.create_counter(
            "orion_agent.tokens.cache_creation",
            description="Cache write input tokens",
        ),
        "tool_errors": meter.create_counter(
            "orion_agent.tool.errors",
            description="Total tool execution errors",
        ),
    }


_metrics: dict[str, Any] = _build_metrics()


def turn_duration() -> Histogram:
    h: Histogram = _metrics["turn_duration"]
    return h


def tool_duration() -> Histogram:
    h: Histogram = _metrics["tool_duration"]
    return h


def api_latency() -> Histogram:
    h: Histogram = _metrics["api_latency"]
    return h


def token_input() -> Counter:
    c: Counter = _metrics["token_input"]
    return c


def token_output() -> Counter:
    c: Counter = _metrics["token_output"]
    return c


def cache_read() -> Counter:
    c: Counter = _metrics["cache_read"]
    return c


def cache_creation() -> Counter:
    c: Counter = _metrics["cache_creation"]
    return c


def tool_errors() -> Counter:
    c: Counter = _metrics["tool_errors"]
    return c
