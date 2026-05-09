# Phase 9 — Worktree + Telemetry 完工記錄

**完成日期**:2026-05-07
**Plan doc**:`docs/phases/09-worktree-telemetry.md`(範圍 C:Cost tracker +
Diagnostic + Sub-agent isolation + OpenTelemetry 切點。**不含** Jaeger / Prometheus /
Grafana docker stack 跟 dashboard JSON,留 Phase 9d。)
**狀態**:✅ `make check` 全綠 — **444 unit tests passed, 0 skipped**(15s),
ruff clean,mypy --strict 131 files clean。

---

## 交付清單

### 新增模組

```
src/orion_agent/
├── telemetry/                            [全新,5 檔]
│   ├── __init__.py
│   ├── pricing.py                        per-token USD 定價表(Claude / GPT)+ get_model_pricing
│   ├── cost_tracker.py                   ModelUsage / SessionCostTracker / global registry
│   ├── diagnostic.py                     redact_pii + safe_log_payload + redact_processor
│   ├── otel.py                           setup_telemetry(graceful no-op)+ tracer/meter +
│   │                                       8 個預先建好的 metric handle
│   └── instrumentation.py                trace_turn / trace_tool_call / trace_api_call +
│                                          record_usage(寫 cost_tracker + OTel counter)
├── sandbox/
│   └── sub_agent_isolation.py            [新] fork_context_for_subagent / release_subagent
└── tools/workdir/                        [全新,3 檔]
    ├── __init__.py
    ├── enter.py                          EnterWorkdirTool(push cwd_stack)
    └── exit.py                           ExitWorkdirTool(pop cwd_stack)
```

### 修改既有檔

```
src/orion_agent/
├── core/state.py                         AgentContext 加 cwd_stack: list[Path]
├── core/conversation.py                  Conversation.send 包 trace_turn span
├── core/query_loop.py                    LLM stream 包 trace_api_call;turn 結束 record_usage
├── core/tool_execution.py                run_one_tool 拆 wrapper + _run_one_tool_inner;
│                                          外層 wrapper start OTel span + duration / errors metric
├── tools/agent/agent_tool.py             改用 fork_context_for_subagent + release_subagent;
│                                          加 sandbox_factory 參數
├── api/routes/sessions.py                新增 GET /sessions/{id}/cost endpoint

pyproject.toml                            opentelemetry-api / opentelemetry-sdk /
                                          opentelemetry-exporter-otlp-proto-grpc
```

### Tests(全新,7 檔,共 44 案例)

```
tests/unit/telemetry/
├── test_pricing.py                4 tests(known / version 後綴 / unknown fallback / 順序)
├── test_cost_tracker.py           10 tests(record / total_cost / cache_hit_ratio / global registry)
├── test_diagnostic.py             9 tests(email / phone / SSN / CC / api keys / safe_log_payload / processor)
├── test_otel.py                   4 tests(no-op / idempotent / metric handle / tracer)
└── test_instrumentation.py        4 tests(trace_turn / tool / api / record_usage)
tests/unit/sandbox/
└── test_sub_agent_isolation.py    7 tests(fork / sandbox_factory / inherit / release / abort 獨立)
tests/unit/tools/workdir/
└── test_workdir.py                6 tests(push / pop / 缺目錄 / 空 stack / 巢狀)
```

---

## 設計決策

### 1. `setup_telemetry` 預設 no-op

沒設 `OTEL_EXPORTER_OTLP_ENDPOINT` → 不啟 SDK exporter,trace / metric API 走
`opentelemetry-api` 預設的 no-op 實作。**instrument 切點仍跑**(start_span /
record),但全部進 NoOp tracer/meter,**零 overhead**。

設了 endpoint(例:`localhost:4317` 給 Jaeger / OTLP Collector)→ 自動 batch
export trace + 10s interval export metric。

呼叫端不需要 if-else 判斷:`tracer / meter` 全域可用,trace_turn 等 wrapper 也都
是 ctx manager,寫起來乾淨。

### 2. `record_usage` 雙寫 cost_tracker + OTel counter

LLM API call 後一次 call:
- 寫 SessionCostTracker(per-session 累計,給 `/sessions/{id}/cost` 看)
- 寫 OTel counter `tokens.input / tokens.output / tokens.cache_read / tokens.cache_creation`(給 Prometheus 看)

兩個視圖各有用途:cost_tracker 是 user-facing「我這場對話花了多少」、OTel 是
ops-facing「整個系統 throughput」。

### 3. Pricing 表 prefix match 處理版本後綴

`claude-sonnet-4-6-20251022` 對不到表 → fallback 到 prefix match
`claude-sonnet-4-6`。Unknown 模型 fallback 到 sonnet 定價(避免 cost=0 假象,
讓 ops 至少看得到「有花錢」)。

### 4. PII redact 的範圍刻意保守

只攻常見 patterns:email / US phone / SSN / CC / Anthropic + OpenAI API key prefix。
**不做 NER**(跨語言 / context-aware redact 留更後)。`safe_log_payload` deep-clone
+ 對 `_SENSITIVE_KEYS`(user_input / prompt / command / url / ...)裡的字串值跑
PII pattern;其他 key 不動。

`redact_processor` 是 structlog processor,直接 chain 進 `processors=[...]`,
caller 不需手動 wrap。

### 5. Sub-agent isolation:fork_context_for_subagent

每個 sub-agent 拿:
- 新 `session_id`(uuid4)
- 新 `abort_event`(`anyio.Event()`,parent abort 不擴散到 child)
- **獨立 sandbox**(透過 `sandbox_factory: () -> SandboxBackend`,sync 或 async
  factory 都吃)— 父子並行 fs 操作不互相干擾
- 父的 `cwd / feature_flags / user_id` 複製
- `sub_agent_depth + 1`(避免無限遞迴)

`release_subagent(handle)` cleanup sandbox(若是 fork 出來的新的;inherit 模式 no-op)。

`AgentTool` 改用此機制,結束自動 release(透過 try/finally)。

### 6. EnterWorkdirTool / ExitWorkdirTool 取代 worktree

不依賴 git(對應 spec § 6 設計決策)。用 `ctx.cwd_stack` push/pop:
- `EnterWorkdir(path=/abs/dir)`:驗存在 → push 舊 cwd → 改 ctx.cwd
- `ExitWorkdir`:pop → 還原

sandbox 啟用時 `EnterWorkdir` 用 `backend.exec(["test", "-d", path])` 驗
sandbox 內目錄存在,**不查 host fs**。sandbox 不啟時走 `Path.exists()`。

### 7. tool_execution 用 wrapper 處理 OTel span

OTel 切點包 async generator 容易踩到 yield + ctx manager 退出時機;
拆 `_run_one_tool_inner` 跑 generator 邏輯,外層 `run_one_tool` 包 span 加 duration / error metric。caller 不需改。

---

## CLI / API 變更

### 新 endpoint

```
GET /sessions/{id}/cost  →  {
  "session_id": "...",
  "user_id": "...",
  "total_cost_usd": 0.0123,
  "cache_hit_ratio": 0.42,
  "total_api_duration_ms": 1234.5,
  "by_model": {
    "claude-sonnet-4-6": {
      "input_tokens": 5000, "output_tokens": 800,
      "cache_creation_tokens": 200, "cache_read_tokens": 4800,
    }
  }
}
```

驗證該 session 屬於 caller 的 user(防跨 user 偷查)。沒任何 LLM call → 回 zero summary。

### 新環境變數

| Env | 用途 |
|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | OTLP gRPC endpoint(例 `localhost:4317`)。**未設 → no-op**(不啟 exporter,但 instrument 仍跑) |

### 新工具 schema

```
EnterWorkdir(path: <abs>)  →  push 舊 cwd 進 stack,改 ctx.cwd
ExitWorkdir()              →  pop stack
```

---

## Verification

```bash
cd orion-agent/api/

make check
# → ruff All checks passed!
# → mypy --strict: 131 files, 0 issues
# → pytest: 444 passed, 0 skipped(15s)

# OTel(無 endpoint)— no-op
uv run orion run --no-mcp --no-memory "echo hi" 2>&1
# 預期:正常跑完,沒 OTel error

# OTel(有 Jaeger)— Phase 9d 給 docker-compose.otel.yml 後可實 trace
OTEL_EXPORTER_OTLP_ENDPOINT="localhost:4317" \
  uv run orion run --no-mcp --no-memory "echo hi"
# 預期:Jaeger UI 能看到 orion_agent.turn / .api / .tool span

# /sessions/{id}/cost
ORION_DB_URL="sqlite+aiosqlite:///:memory:" uv run orion serve --port 8765 &
TOKEN=$(curl -s -X POST http://127.0.0.1:8765/auth/login -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":""}' | jq -r .token)
SID=$(curl -s -X POST http://127.0.0.1:8765/sessions -H "Authorization: Bearer $TOKEN" | jq -r .session_id)
# (之後跑些對話)
curl -s http://127.0.0.1:8765/sessions/$SID/cost -H "Authorization: Bearer $TOKEN" | jq
```

---

## Phase 9 故意先不做(都已開新 phase plan)

| 項目 | 留給 |
|---|---|
| Jaeger / Prometheus / Grafana docker-compose stack | Phase 9d(`docs/phases/plan/9d-grafana-stack.md`) |
| Grafana dashboard JSON(per-user / per-tool / per-turn 視圖) | Phase 9d |
| OTLP HTTP exporter / multi-tenant attribute filtering | Phase 9d |
| Quota engine(用 cost_tracker 做 per-user / per-org 限額) | Phase 11+ |
| Token budget tier(免費 / Pro / Team) | Phase 11+ |
| Distributed tracing(API → MCP server → tool subprocess) | Phase 10+ |
| Real-time cost stream over WebSocket(turn 結束推總費用) | Phase 10+ |
| Anomaly detection(latency / error spike alert) | Phase 11+ |

---

## 風險與已緩解

| 風險 | 緩解 |
|---|---|
| OTel SDK 沒 endpoint 啟動會 spam log | 用 lazy import + try/except,失敗 fall back to no-op |
| async generator 包 OTel ctx manager 容易 yield 卡死 | tool_execution 拆 inner / wrapper,wrapper 用 manual `start_span` + `try/finally end()` |
| Pricing 表會過時 | per-token 數值在 pricing.py 集中,後續一處改即可;測試 enforce sonnet < opus 不會反過來 |
| PII redact 不完美(漏中文 / 全形 / 無 NER) | 文件記載「保守 pattern,不取代 vault」;真敏感場景需加 vault layer |
| Sub-agent abort 共用問題 | `fork_context_for_subagent` 建新 `anyio.Event()`,父子完全獨立(已 unit test 驗證) |
| iCloud 干擾 OTel SDK 載入 | 跑前 `chflags -R nohidden .venv && find .venv -name "* [2-9]*" -delete`(暫時 workaround,長期改 ~/code/) |

---

## Tests 摘要

| Suite | 數量 | 說明 |
|---|---|---|
| Phase 0–8 既有 | 400 | 全綠不動 |
| **Phase 9 telemetry** | 31 | pricing(4)+ cost_tracker(10)+ diagnostic(9)+ otel(4)+ instrumentation(4) |
| **Phase 9 sub-agent isolation** | 7 | fork / sandbox_factory / inherit / release / 獨立 abort |
| **Phase 9 workdir tools** | 6 | enter / exit / 巢狀 / 空 stack / 缺目錄 |
| **總計** | **444** | mypy --strict 131 files / ruff 全綠 |
