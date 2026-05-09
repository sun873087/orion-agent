# Phase 9d — Grafana / Jaeger / Prometheus Stack + Dashboards

**狀態**:📋 Plan(等實際 ops 環境決定 backend 廠商)
**前置**:Phase 9 完成(OTel API + tracer + 4 切點 + cost_tracker)
**估時**:1-2 天

## 動機

Phase 9 範圍 C 已交付 OTel **instrumentation**(SDK + 4 個主切點 + 8 個 metric)。
**沒做**部署側:
- Jaeger / Prometheus / Grafana 怎麼啟
- Grafana dashboard JSON(turn latency / tool hot-spot / cost / cache hit ratio)
- 實 trace / metric 端到端跑通的 demo

production 真要拿 Phase 9 觀測性,需要這層。本 phase 補完。

## 範圍

### 做

| 項目 | 說明 |
|---|---|
| **`deploy/observability/docker-compose.yml`** | Jaeger(all-in-one)+ Prometheus + Grafana,one-line up |
| **OTel Collector**(可選) | otel-collector 中介,統一 receive → fan-out 到 Jaeger + Prometheus(否則 SDK 直接送 Jaeger,metric 用 OTel SDK 內建 Prometheus exporter) |
| **Grafana datasources auto-provision** | provisioning/datasources/jaeger.yaml + prometheus.yaml |
| **Dashboard JSON** | `dashboards/orion-agent.json`:turn duration p95 / tool hot-spot / cost per user / cache hit ratio / error rate |
| **README** | `deploy/observability/README.md` 跑流程 + screenshot |
| **OTLP HTTP exporter** | 預設 gRPC,但 K8s 環境常開 HTTP-only;加 `OTEL_EXPORTER_OTLP_PROTOCOL=http/protobuf` 支援 |
| **Multi-tenant attribute filter** | Grafana variable `user_id` 切視圖 |
| **smoke test** | 端到端跑 1 conversation → Jaeger UI 看到 trace、Grafana 看到 metric |

### 不做

- Anomaly alert(latency / error spike)→ Phase 11+
- Cost-based budget alert(超 quota 推 webhook)→ Phase 11+(配合 quota engine)
- Distributed tracing 跨 MCP server / tool subprocess → Phase 10+
- Loki / log aggregation → 可選,留 Ops 自選

## 檔案結構

```
deploy/observability/
├── docker-compose.yml                  Jaeger + Prometheus + Grafana(+ optional otel-collector)
├── otel-collector-config.yaml          (可選)collector receivers/processors/exporters
├── prometheus.yml                      scrape config
└── grafana/
    ├── provisioning/
    │   ├── datasources/
    │   │   ├── jaeger.yaml
    │   │   └── prometheus.yaml
    │   └── dashboards/
    │       └── orion-agent.yaml        provider config
    └── dashboards/
        └── orion-agent.json            主 dashboard

src/orion_agent/telemetry/otel.py       [改] 加 OTLP HTTP exporter(env OTEL_EXPORTER_OTLP_PROTOCOL)

deploy/README.md                        [改] 加 observability stack section
```

## 實作順序(8 步)

| Step | 工作 |
|---|---|
| 1 | otel.py 加 HTTP exporter(用 `opentelemetry-exporter-otlp-proto-http`)|
| 2 | `deploy/observability/docker-compose.yml`:Jaeger + Prom + Grafana |
| 3 | Grafana datasources provisioning |
| 4 | `dashboards/orion-agent.json`:turn / tool / api / cost panel |
| 5 | smoke test:跑 conversation → 驗 Jaeger UI 有 span、Grafana 有 metric |
| 6 | 截圖貼 README |
| 7 | 主 docs/observability.md 寫使用指南(env、port、auth) |
| 8 | unit test for HTTP exporter env override |

## Dashboard 設計

四個主面板:

1. **Turn Latency Histogram(p50 / p95 / p99)**
   - PromQL: `histogram_quantile(0.95, rate(orion_agent_turn_duration_milliseconds_bucket[5m]))`
   - 切片:by `session_id`(或 `user_id` if 上 attribute)

2. **Tool Hot-spot**
   - bar chart:`sum by (tool_name)(rate(orion_agent_tool_duration_milliseconds_count[5m]))`
   - p95 latency by tool
   - error rate by tool

3. **Cost Per User**
   - timeseries:`sum by (user_id)(orion_agent_tokens_input_total * <unit_price>)`
   - 注意:單位價在 Grafana 算麻煩,真要做用 Phase 11 quota engine 算好寫 metric

4. **Cache Hit Ratio**
   - gauge: `sum(rate(orion_agent_tokens_cache_read_total[5m])) / sum(rate(orion_agent_tokens_input_total[5m] + orion_agent_tokens_cache_read_total[5m] + orion_agent_tokens_cache_creation_total[5m]))`

## docker-compose.yml(草稿)

```yaml
version: "3.8"
services:
  jaeger:
    image: jaegertracing/all-in-one:1.60
    environment:
      COLLECTOR_OTLP_ENABLED: "true"
    ports:
      - "16686:16686"   # UI
      - "4317:4317"     # OTLP gRPC
      - "4318:4318"     # OTLP HTTP

  prometheus:
    image: prom/prometheus:v2.55.0
    volumes:
      - ./prometheus.yml:/etc/prometheus/prometheus.yml:ro
    ports:
      - "9090:9090"

  grafana:
    image: grafana/grafana:11.3.0
    ports:
      - "3000:3000"
    environment:
      GF_AUTH_ANONYMOUS_ENABLED: "true"
      GF_AUTH_ANONYMOUS_ORG_ROLE: Viewer
    volumes:
      - ./grafana/provisioning:/etc/grafana/provisioning
      - ./grafana/dashboards:/var/lib/grafana/dashboards
      - grafana_data:/var/lib/grafana

volumes:
  grafana_data:
```

## Verification

```bash
# 1. 起 stack
docker compose -f deploy/observability/docker-compose.yml up -d

# 2. 跑 conversation 並接 OTel
OTEL_EXPORTER_OTLP_ENDPOINT="localhost:4317" \
  uv run orion run --no-mcp --no-memory "test telemetry"

# 3. 看 Jaeger UI
open http://localhost:16686
# 預期:看到 service "orion-agent" 的 trace,內含 orion_agent.turn / .api / .tool span

# 4. 看 Grafana
open http://localhost:3000
# 預期:dashboard "Orion Agent Overview" 自動載入,看到 metric

# 5. cost endpoint
curl -s http://127.0.0.1:8000/sessions/$SID/cost -H "Authorization: Bearer $TOKEN" | jq
```

## 風險

| 風險 | 緩解 |
|---|---|
| Grafana dashboard JSON 跨 Grafana 版本 schema 不相容 | 鎖 Grafana 版本(v11.3+),dashboard JSON 只用 stable panel types |
| Cardinality 爆炸(每個 user_id 一個 series) | 不把 user_id 當 metric label;改寫進 trace span attribute(Jaeger 才看得到 per-user) |
| OTel Collector 多一層延遲 | dev / 小規模直接 SDK→Jaeger;production 才接 collector |
| Grafana auth 預設關 → public exposure | 設 `GF_SECURITY_ADMIN_PASSWORD`;production 上 Ingress 加 OAuth proxy |
| Prometheus retention | 預設 15 天;long-term 用 Thanos / Mimir,Phase 10+ 設計 |

## 完成 Phase 9d 後

進 Phase 10(tools / performance)或 Phase 11(input pipeline)。
