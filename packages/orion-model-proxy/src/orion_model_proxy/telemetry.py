"""OpenTelemetry skeleton。

設計目標:不增加硬依賴(production 才 pip install opentelemetry-api),
env 沒設 / 套件沒裝 → 全 no-op,proxy 照跑。

用法:
    from orion_model_proxy.telemetry import span
    with span("proxy.openai_forward", user_id=uid, model=m):
        ...

OTEL_EXPORTER_OTLP_ENDPOINT 設了才會真 emit;沒設 → context manager no-op。
"""

from __future__ import annotations

import contextlib
import os
from typing import Any, Iterator

_initialized = False
_tracer: Any = None


def _try_init() -> None:
    """Lazy init — 只在首次 span() 呼叫時嘗試。"""
    global _initialized, _tracer
    if _initialized:
        return
    _initialized = True
    if not os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT"):
        return # 沒設,no-op
    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(
            resource=Resource.create({"service.name": "orion-model-proxy"})
        )
        provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("orion-model-proxy")
    except ImportError:
        # OTel 套件沒裝 — silently no-op
        pass


@contextlib.contextmanager
def span(name: str, **attrs: Any) -> Iterator[None]:
    """Span context manager。env 沒設 / OTel 沒裝 → yield 但不 emit。"""
    _try_init()
    if _tracer is None:
        yield
        return
    with _tracer.start_as_current_span(name) as sp:
        for k, v in attrs.items():
            try:
                sp.set_attribute(k, v)
            except Exception: # noqa: BLE001
                pass
        yield


__all__ = ["span"]
