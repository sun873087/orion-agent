# Phase 9:Worktree + Telemetry(子 agent 隔離 + 觀測性)

## 速覽

- **預計時程**:2-3 週
- **前置 Phase**:Phase 7(sandbox)、Phase 8(hook 系統)
- **後續 Phase**:Phase 10 用 telemetry 找性能瓶頸
- **主要交付物**:
  - Worktree 替代方案(用 sandbox 隔離,改 cwd 而非 git worktree)
  - Sub-agent isolation(每個子 agent 獨立 ctx + sandbox)
  - OpenTelemetry 整合(對應 services/analytics)
  - DiagnosticTracking(PII-safe)
  - cost-tracker per-session 累計
  - Per-tool latency / token 觀測

## 1. 目標與動機

兩個獨立但相關的目標:

```
Worktree 替代:
  TS 用 git worktree 給子 agent 用(隔離 cwd)
  Python 已有 Phase 7 的 sandbox,直接用 sandbox 取代 worktree
  更乾淨、不限定 git 環境

Telemetry:
  Phase 1-8 跑通了,但黑盒
  加 OpenTelemetry → 看每個 turn / 工具 / hook 的延遲、token、錯誤率
  找瓶頸、優化、debug、計費
```

**對應 docs**:
- [docs/06 模組 11](../06-harness-engineering.md) 子 Agent 編排
- [docs/06 橫切關注點 - 可觀測性](../06-harness-engineering.md)

完成本 phase 後,系統 production-ready 並可優化。

## 2. TS 源檔映射

| Python 模組 | 對應 TS 源檔 | 注意事項 |
|---|---|---|
| `src/sandbox/sub_agent_isolation.py` | `src/tools/AgentTool/forkSubagent.ts`、`src/tools/EnterWorktreeTool/` | 用 sandbox 取代 worktree |
| `src/telemetry/otel.py` | `src/services/analytics/` 多檔 | OpenTelemetry 整合 |
| `src/telemetry/diagnostic.py` | `src/services/diagnosticTracking.ts` | PII-safe 診斷 |
| `src/telemetry/cost_tracker.py` | `src/cost-tracker.ts` | per-session token / cost 累計 |
| `src/telemetry/instrumentation.py` | `src/utils/queryProfiler.ts` | profiler 切點 |

## 3. 任務拆解

### Week 1:Sub-agent isolation + Worktree 替代

- [ ] 1.1 `sandbox/sub_agent_isolation.py`:`fork_for_subagent` — 父 sandbox + 新 cwd / 新 ctx
- [ ] 1.2 改造 Phase 1 的 AgentTool:子 agent 自動取得新 sandbox
- [ ] 1.3 新工具 `EnterWorkdirTool` / `ExitWorkdirTool`(取代 EnterWorktreeTool):用 sandbox 切 cwd
- [ ] 1.4 子 agent 結束時釋放 sandbox 回 pool
- [ ] 1.5 測試:父子 agent 並行操作不互相干擾

### Week 2:OpenTelemetry 基礎

- [ ] 2.1 加入依賴:`opentelemetry-api`、`opentelemetry-sdk`、`opentelemetry-exporter-otlp`
- [ ] 2.2 `telemetry/otel.py`:setup tracer / meter / exporter
- [ ] 2.3 instrument 關鍵切點:
  - 每 turn(`Conversation.submit_message`)
  - 每工具呼叫(`StreamingToolExecutor`)
  - 每 API 呼叫(`AnthropicStreamingClient`)
  - 每 hook 執行(`HookRegistry.fire`)
- [ ] 2.4 metrics:turn_duration / tool_duration / api_latency / token_count / cache_hit_ratio
- [ ] 2.5 docker-compose 加 Jaeger / Prometheus / Grafana

### Week 3:Cost tracker + Diagnostic + 整合

- [ ] 3.1 `telemetry/cost_tracker.py`:per-session usage 累計
- [ ] 3.2 各模型定價(從 anthropic API response 抓)
- [ ] 3.3 `telemetry/diagnostic.py`:PII-safe 結構化 log
- [ ] 3.4 整合 quota(Phase 7)— cost 追蹤觸發 quota check
- [ ] 3.5 Grafana dashboard JSON(per-user / per-tool / per-turn 視圖)
- [ ] 3.6 測試:跑對話 → Jaeger 看完整 trace、Grafana 看 metrics
- [ ] 3.7 寫 Phase 9 心得

## 4. 模組架構與檔案

```
src/claude_agent_py/
├── sandbox/
│   └── sub_agent_isolation.py         # ◀ NEW fork sandbox 給子 agent
│
├── telemetry/
│   ├── __init__.py
│   ├── otel.py                        # ◀ NEW OpenTelemetry setup
│   ├── instrumentation.py             # ◀ NEW 關鍵切點包裝
│   ├── cost_tracker.py                # ◀ NEW per-session usage
│   ├── diagnostic.py                  # ◀ NEW PII-safe log
│   └── pricing.py                     # ◀ NEW 模型定價表
│
└── tools/
    └── workdir/
        ├── enter.py                   # ◀ NEW EnterWorkdirTool(取代 EnterWorktreeTool)
        └── exit.py                    # ◀ NEW ExitWorkdirTool

docker-compose.yml                     # ◀ 擴充:加 Jaeger / Prometheus / Grafana

dashboards/                            # ◀ NEW
└── claude-agent.json                  # Grafana dashboard
```

## 5. Python Skeleton

### 5.1 `sandbox/sub_agent_isolation.py`

```python
"""子 agent 隔離。對應 TS forkSubagent + EnterWorktreeTool。"""
from __future__ import annotations
from dataclasses import replace
from uuid import uuid4
import anyio

from claude_agent_py.core.state import AgentContext
from claude_agent_py.sandbox.docker import Sandbox
from claude_agent_py.sandbox.pool import SandboxPool


async def fork_context_for_subagent(
    parent: AgentContext,
    *,
    pool: SandboxPool,
    inherit_cwd: bool = False,
) -> AgentContext:
    """為子 agent 產生新 ctx + 新 sandbox。

    對應 TS forkSubagent:
      - 新 session_id(子 agent 獨立)
      - 新 abort_event(父 abort 不影響子,反之亦然)
      - 新 sandbox(父子並行操作 fs 不互相干擾)
      - 限縮 tools(子 agent 可能拿不到所有工具)
    """
    new_session_id = uuid4()
    new_sandbox = await pool.acquire(str(new_session_id))

    return replace(
        parent,
        session_id=new_session_id,
        abort_event=anyio.Event(),
        sandbox=new_sandbox,
        # cwd:預設沿用父的(語意延續)
        cwd=parent.cwd if inherit_cwd else parent.cwd,
        # token_budget:子 agent 算父預算的 ratio?還是無限?設計決策
        token_budget=parent.token_budget,
        # feature_flags:複製
        feature_flags=dict(parent.feature_flags),
    )


async def release_subagent_context(ctx: AgentContext, pool: SandboxPool) -> None:
    """子 agent 結束釋放 sandbox。"""
    await pool.release(str(ctx.session_id))
```

### 5.2 `tools/workdir/enter.py`

```python
"""EnterWorkdirTool — 取代 EnterWorktreeTool。

不用 git worktree(會限定 git repo),直接在 sandbox 內切目錄。
"""
from __future__ import annotations
from typing import AsyncIterator
from pathlib import Path

from claude_agent_py.core.tool import Tool, ToolInput, ToolEvent, TextEvent, ErrorEvent
from claude_agent_py.core.state import AgentContext


class EnterWorkdirInput(ToolInput):
    path: str
    """新 cwd(在 sandbox 內的絕對路徑)。"""


class EnterWorkdirTool:
    name = "EnterWorkdir"
    description = "Switch to a different directory inside the sandbox."
    input_schema = EnterWorkdirInput

    def is_concurrency_safe(self, input: EnterWorkdirInput) -> bool:
        return False  # 改 ctx,不能並發

    async def call(
        self, input: EnterWorkdirInput, ctx: AgentContext,
    ) -> AsyncIterator[ToolEvent]:
        target = Path(input.path)
        if not target.is_absolute():
            yield ErrorEvent(message="Path must be absolute")
            return

        # 注意:cwd 在 sandbox 內,不直接改 host fs
        # 實作:在 ctx 標記 sandbox 內的 cwd
        ctx.cwd = target  # 這裡是 sandbox 內視角
        yield TextEvent(text=f"Now in {target}")
```

### 5.3 `telemetry/otel.py`

```python
"""OpenTelemetry setup。"""
from __future__ import annotations
import os
from opentelemetry import trace, metrics
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.resources import Resource
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.exporter.otlp.proto.grpc.metric_exporter import OTLPMetricExporter
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader


def setup_telemetry() -> None:
    """初始化 OTel。"""
    resource = Resource.create({
        "service.name": "claude-agent-py",
        "service.version": "0.1.0",
    })

    # Tracer
    tracer_provider = TracerProvider(resource=resource)
    otlp_endpoint = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "localhost:4317")
    span_exporter = OTLPSpanExporter(endpoint=otlp_endpoint, insecure=True)
    tracer_provider.add_span_processor(BatchSpanProcessor(span_exporter))
    trace.set_tracer_provider(tracer_provider)

    # Meter
    metric_exporter = OTLPMetricExporter(endpoint=otlp_endpoint, insecure=True)
    reader = PeriodicExportingMetricReader(metric_exporter, export_interval_millis=10_000)
    meter_provider = MeterProvider(resource=resource, metric_readers=[reader])
    metrics.set_meter_provider(meter_provider)


# 全域可用的 tracer / meter
tracer = trace.get_tracer("claude-agent-py")
meter = metrics.get_meter("claude-agent-py")

# 預先建立常用 metric
turn_duration = meter.create_histogram(
    "claude_agent.turn.duration",
    unit="ms",
    description="End-to-end turn duration",
)

tool_duration = meter.create_histogram(
    "claude_agent.tool.duration",
    unit="ms",
    description="Single tool call duration",
)

api_latency = meter.create_histogram(
    "claude_agent.api.latency",
    unit="ms",
    description="Anthropic API latency",
)

token_input = meter.create_counter(
    "claude_agent.tokens.input",
    description="Total input tokens",
)

token_output = meter.create_counter(
    "claude_agent.tokens.output",
    description="Total output tokens",
)

cache_hit_input = meter.create_counter(
    "claude_agent.tokens.cache_read",
    description="Cache-hit input tokens",
)
```

### 5.4 `telemetry/instrumentation.py`(關鍵切點)

```python
"""把 OTel 切點包到 Phase 1-8 的關鍵函式。"""
from __future__ import annotations
import time
from contextlib import asynccontextmanager

from claude_agent_py.telemetry.otel import (
    tracer, turn_duration, tool_duration, api_latency,
    token_input, token_output, cache_hit_input,
)


@asynccontextmanager
async def trace_turn(session_id: str, user_id: str | None):
    """包整個 turn。"""
    with tracer.start_as_current_span(
        "claude_agent.turn",
        attributes={
            "session_id": session_id,
            "user_id": user_id or "anonymous",
        },
    ) as span:
        start = time.monotonic()
        try:
            yield span
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            turn_duration.record(duration_ms, {"session_id": session_id})


@asynccontextmanager
async def trace_tool_call(tool_name: str, tool_use_id: str, session_id: str):
    """包單一工具執行。"""
    with tracer.start_as_current_span(
        "claude_agent.tool",
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
            raise
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            tool_duration.record(duration_ms, {"tool.name": tool_name})


@asynccontextmanager
async def trace_api_call(model: str, session_id: str):
    """包 Anthropic API 呼叫。"""
    with tracer.start_as_current_span(
        "claude_agent.api",
        attributes={"model": model, "session_id": session_id},
    ) as span:
        start = time.monotonic()
        try:
            yield span
        finally:
            duration_ms = (time.monotonic() - start) * 1000
            api_latency.record(duration_ms, {"model": model})


def record_usage(usage: dict, session_id: str, model: str) -> None:
    """從 anthropic response.usage 紀錄 token。"""
    attrs = {"session_id": session_id, "model": model}
    token_input.add(usage.get("input_tokens", 0), attrs)
    token_output.add(usage.get("output_tokens", 0), attrs)
    cache_hit_input.add(usage.get("cache_read_input_tokens", 0), attrs)
```

整合到 `Conversation.submit_message`(範例):

```python
async def submit_message(self, prompt: str):
    async with trace_turn(str(self.ctx.session_id), self.user_id):
        async for msg in query_loop(...):
            yield msg
```

### 5.5 `telemetry/cost_tracker.py`

```python
"""Per-session cost tracker。對應 TS cost-tracker.ts。"""
from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict

from claude_agent_py.telemetry.pricing import get_model_pricing


@dataclass
class ModelUsage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_tokens: int = 0
    cache_read_tokens: int = 0


@dataclass
class SessionCostTracker:
    session_id: str
    user_id: str | None = None
    by_model: dict[str, ModelUsage] = field(default_factory=lambda: defaultdict(ModelUsage))
    total_api_duration_ms: float = 0.0

    def record(self, model: str, usage: dict, duration_ms: float) -> None:
        m = self.by_model[model]
        m.input_tokens += usage.get("input_tokens", 0)
        m.output_tokens += usage.get("output_tokens", 0)
        m.cache_creation_tokens += usage.get("cache_creation_input_tokens", 0)
        m.cache_read_tokens += usage.get("cache_read_input_tokens", 0)
        self.total_api_duration_ms += duration_ms

    def total_cost_usd(self) -> float:
        total = 0.0
        for model, usage in self.by_model.items():
            pricing = get_model_pricing(model)
            total += (
                usage.input_tokens * pricing.input_per_token
                + usage.output_tokens * pricing.output_per_token
                + usage.cache_creation_tokens * pricing.cache_creation_per_token
                + usage.cache_read_tokens * pricing.cache_read_per_token
            )
        return total

    def cache_hit_ratio(self) -> float:
        total_input = sum(
            u.input_tokens + u.cache_creation_tokens + u.cache_read_tokens
            for u in self.by_model.values()
        )
        cache_read = sum(u.cache_read_tokens for u in self.by_model.values())
        return cache_read / total_input if total_input > 0 else 0.0


# 全域 registry(per-session)
_session_trackers: dict[str, SessionCostTracker] = {}


def get_or_create_tracker(session_id: str, user_id: str | None = None) -> SessionCostTracker:
    if session_id not in _session_trackers:
        _session_trackers[session_id] = SessionCostTracker(session_id, user_id)
    return _session_trackers[session_id]


def get_session_summary(session_id: str) -> dict:
    """供 /sessions/{id}/cost API 使用。"""
    t = _session_trackers.get(session_id)
    if t is None:
        return {}
    return {
        "total_cost_usd": t.total_cost_usd(),
        "cache_hit_ratio": t.cache_hit_ratio(),
        "by_model": {
            model: {
                "input_tokens": u.input_tokens,
                "output_tokens": u.output_tokens,
                "cache_read_tokens": u.cache_read_tokens,
            }
            for model, u in t.by_model.items()
        },
        "total_api_duration_ms": t.total_api_duration_ms,
    }
```

### 5.6 `telemetry/pricing.py`

```python
"""模型定價表。"""
from __future__ import annotations
from dataclasses import dataclass


@dataclass
class ModelPricing:
    input_per_token: float
    output_per_token: float
    cache_creation_per_token: float
    cache_read_per_token: float


# 2026 年 5 月參考價(per token,不是 per million)
PRICING_TABLE = {
    "claude-opus-4-7": ModelPricing(
        input_per_token=15e-6, output_per_token=75e-6,
        cache_creation_per_token=18.75e-6, cache_read_per_token=1.5e-6,
    ),
    "claude-sonnet-4-6": ModelPricing(
        input_per_token=3e-6, output_per_token=15e-6,
        cache_creation_per_token=3.75e-6, cache_read_per_token=0.3e-6,
    ),
    "claude-haiku-4-5": ModelPricing(
        input_per_token=1e-6, output_per_token=5e-6,
        cache_creation_per_token=1.25e-6, cache_read_per_token=0.1e-6,
    ),
}


def get_model_pricing(model: str) -> ModelPricing:
    """找最匹配的 pricing(處理版本後綴等)。"""
    if model in PRICING_TABLE:
        return PRICING_TABLE[model]
    # fallback:取前綴 match
    for key, pricing in PRICING_TABLE.items():
        if model.startswith(key):
            return pricing
    # 預設用 sonnet 定價(避免 0)
    return PRICING_TABLE["claude-sonnet-4-6"]
```

### 5.7 `telemetry/diagnostic.py`

```python
"""PII-safe 結構化 log。對應 TS diagnosticTracking.ts。"""
from __future__ import annotations
import re
import structlog


# 簡單 PII 規則
PII_PATTERNS = {
    "email": re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"),
    "phone": re.compile(r"\b\d{3}[-.\s]?\d{3}[-.\s]?\d{4}\b"),
    "ssn": re.compile(r"\b\d{3}-\d{2}-\d{4}\b"),
    "credit_card": re.compile(r"\b\d{4}[-\s]?\d{4}[-\s]?\d{4}[-\s]?\d{4}\b"),
}


def redact_pii(text: str) -> str:
    """簡單 PII redaction。"""
    for name, pattern in PII_PATTERNS.items():
        text = pattern.sub(f"[REDACTED_{name.upper()}]", text)
    return text


# 自動 redact processor
def redact_processor(logger, method_name, event_dict):
    if "user_input" in event_dict and isinstance(event_dict["user_input"], str):
        event_dict["user_input"] = redact_pii(event_dict["user_input"])
    if "tool_input" in event_dict and isinstance(event_dict["tool_input"], dict):
        # 對特定 key redact
        for k in ("content", "command", "url"):
            if k in event_dict["tool_input"] and isinstance(
                event_dict["tool_input"][k], str
            ):
                event_dict["tool_input"][k] = redact_pii(event_dict["tool_input"][k])
    return event_dict


# 設定
structlog.configure(
    processors=[
        structlog.processors.TimeStamper(fmt="iso"),
        redact_processor,
        structlog.processors.JSONRenderer(),
    ],
)


log = structlog.get_logger("claude_agent_py.diagnostic")
```

### 5.8 docker-compose 擴充

```yaml
# 加到 Phase 7 的 docker-compose.yml

services:
  jaeger:
    image: jaegertracing/all-in-one:latest
    ports:
      - "16686:16686"  # UI
      - "4317:4317"     # OTLP gRPC
    environment:
      - COLLECTOR_OTLP_ENABLED=true

  prometheus:
    image: prom/prometheus
    volumes:
      - ./monitoring/prometheus.yml:/etc/prometheus/prometheus.yml
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana
    ports:
      - "3000:3000"
    volumes:
      - grafana_data:/var/lib/grafana
      - ./dashboards:/etc/grafana/provisioning/dashboards
```

## 6. 設計決策與取捨

### 為何用 sandbox 取代 git worktree?

TS 用 git worktree 的優點:
- 同 repo 多 working tree,共用 .git
- 自然支援 git 工作流

但**限制**:
- 必須是 git repo
- 並行 commit 還是會碰

Phase 7 已有 sandbox,**取代 worktree 更通用**:
- 任意目錄都行(不限 git)
- 完全 fs 隔離
- 並行操作零干擾

### 為何 OpenTelemetry 而非自己寫 logger?

- **業界標準**:Jaeger / Datadog / Honeycomb / Grafana 都吃 OTel
- **vendor-neutral**:換後端不改 instrumentation
- **distributed tracing**:跨 service trace ID 自動 propagate(若未來拆 microservice)

對應 TS 的 `services/analytics/` 也是用第三方(Datadog),Python 用 OTel 是同樣思路。

### 為何 cost tracker 是 in-memory?

Phase 9 的 cost tracker 與 Phase 7 的 quota 分工:
- **cost tracker**:精確記錄(per-session,fine-grained)
- **quota**:粗略限制(per-user / 日 / 月,Redis atomic)

Phase 9 cost tracker 在 process 內。重啟丟資料,沒關係(已寫到 OTel)。Production 應雙寫 DB。

### 為何 PII redaction 不完整?

正則只能處理 obvious patterns。完整 PII 處理需要:
- ML-based detection(姓名、地址)
- 領域特定(醫療 / 金融)

Phase 9 是 80% 解(redact email / phone / SSN / credit card)。完整 PII compliance 留給專業 library / 服務。

### Phase 9 故意不做的

| 項目 | 留給哪個 phase |
|---|---|
| 完整 PII compliance(GDPR / HIPAA)| 不做(scope 外) |
| 進階 sandbox(VM 級隔離) | 不做 |
| Logs aggregation 進 ELK | 不做(OTel 即可) |
| Auto-scaling based on telemetry | 不做(K8s HPA 自己做) |

## 7. 驗收標準

### 自動測試

```bash
pytest tests/sandbox/ tests/telemetry/ -v
```

關鍵測試:

- `test_subagent_isolation.py`:父子 agent 寫不同 fs 不互相影響
- `test_subagent_abort.py`:父 abort 不影響子(反之亦然)
- `test_otel_setup.py`:tracer 初始化、span 正確 record
- `test_cost_calculation.py`:per-model 累加、cache_read 比例計算
- `test_pii_redaction.py`:email / phone / SSN / credit card 被 mask

### 手動驗證

```bash
# 啟完整 stack
docker-compose up -d

# 跑對話
curl -X POST http://localhost:8000/chat/sessions ...

# 看 Jaeger trace
open http://localhost:16686
# 找 service: claude-agent-py
# 看 turn → tool → api 的階層 span

# 看 Grafana
open http://localhost:3000
# Import dashboard: dashboards/claude-agent.json
# 看 turn duration p95 / token rate / cache hit ratio
```

### 整合驗證

跑 1 小時負載測試,觀察:

- Jaeger 顯示完整 trace(turn → tool → api 巢狀)
- Grafana 顯示 metrics(turn p99 < 30s、cache hit > 70%)
- cost tracker per-session 數字合理($0.001-0.10/turn 範圍)
- log 沒有 raw email / phone(都被 redact)

## 8. 常見踩雷

### 踩雷 1:OTel exporter 慢拖累 hot path

OTLP exporter 預設同步 export → 拖累 turn 延遲。要用 BatchSpanProcessor / PeriodicExportingMetricReader(已在 skeleton),非阻塞。

### 踩雷 2:Sub-agent sandbox 沒釋放

子 agent 結束時 forget release sandbox → pool 漏。`AgentTool` 必須 try / finally:

```python
ctx_for_child = await fork_context_for_subagent(...)
try:
    async for msg in run_subagent(...):
        yield msg
finally:
    await release_subagent_context(ctx_for_child, pool)
```

### 踩雷 3:OTel context propagation across async

`asyncio.create_task` 預設不傳遞 OTel context。要用 OTel 的 `attach` / `detach` 或 task name 對應。

`trace.use_span(...)` 在 task 內手動 attach。

### 踩雷 4:Cache hit ratio 算錯

`cache_read / total_input` vs `cache_read / (input + cache_creation + cache_read)`。Anthropic 的 input_tokens 可能不含 cache_read。看 SDK 文件確認。

### 踩雷 5:Pricing 過時

模型定價會變(降價 / 新模型)。pricing.py 寫死 → 過時計費錯。要:
- 固定週期(每月)更新 pricing table
- 或從 Anthropic API 動態抓(若有提供)

### 踩雷 6:PII redaction false positive

正則太貪婪 → 把不是 email 的東西也 mask。例:`a@b.c` 會被誤 redact 成 email。要小心 regex 邊界。

或反過來:false negative 漏 mask 也是問題。Phase 9 是 best-effort,完整方案要 ML library。

### 踩雷 7:OpenTelemetry 版本相容

OTel Python SDK 各 package(api / sdk / instrumentation / exporter)必須版本一致。要 pin 全部:

```toml
opentelemetry-api = "1.27.0"
opentelemetry-sdk = "1.27.0"
opentelemetry-exporter-otlp = "1.27.0"
```

## 9. 參考資料

### docs/01-11

- [docs/06 模組 11](../06-harness-engineering.md) — Sub-agent 編排
- [docs/06 橫切關注點 - 可觀測性](../06-harness-engineering.md)

### TS 源檔

- `src/tools/AgentTool/forkSubagent.ts` — 子 agent ctx fork 邏輯
- `src/tools/EnterWorktreeTool/`、`ExitWorktreeTool/` — worktree 工具
- `src/services/analytics/` 多檔 — Datadog 整合
- `src/services/diagnosticTracking.ts` — PII-safe 日誌
- `src/cost-tracker.ts` — token/cost 累計

### 外部資源

- [OpenTelemetry Python](https://opentelemetry.io/docs/instrumentation/python/)
- [OTel exporter best practices](https://opentelemetry.io/docs/concepts/sdk-configuration/general-sdk-configuration/)
- [Jaeger](https://www.jaegertracing.io/)
- [Prometheus + Grafana for Python](https://prometheus.io/docs/instrumenting/clientlibs/)
- [structlog](https://www.structlog.org/)
- [Anthropic pricing](https://www.anthropic.com/pricing)

## 完成檢查表

- [ ] Sub-agent 用獨立 sandbox + ctx
- [ ] EnterWorkdirTool 取代 EnterWorktreeTool
- [ ] OTel tracer / meter setup
- [ ] 4 個關鍵切點 instrumented(turn / tool / api / hook)
- [ ] Per-session cost tracker 正確累計
- [ ] PII redaction 對 obvious patterns 有效
- [ ] Jaeger trace 看到完整階層
- [ ] Grafana dashboard 有 metrics
- [ ] 寫 Phase 9 心得

完成後進入 [Phase 10:Tools + Performance](./10-tools-performance.md)。
