# Orion Model Proxy

**Phase 31-X MVP**。HTTP service 統一接 Anthropic / OpenAI / Ollama,3 個 app
(CLI / Chat / Cowork)透過 env var 切過去就用 proxy,不必各自管 API key。

**實作位置**:`packages/orion-model-proxy/`

```
packages/orion-model-proxy/
├── pyproject.toml
└── src/orion_model_proxy/
    ├── __init__.py
    ├── __main__.py        entrypoint(uv run orion-model-proxy)
    └── server.py          FastAPI app
```

## 為什麼

| 痛點 | Proxy 解什麼 |
|---|---|
| `OPENAI_API_KEY` 等 3 個 app 各放 `.env` | 一處(proxy 機)放完所有 host 共用 |
| Cost 每 app 各算各的 | 集中 DB 看全 user 花費 |
| Cowork 90 MB sidecar 內 bundle 全 provider SDK | 將來可瘦身(下一階段) |
| 想做 routing(`auto-fast` → cheap model)| Proxy 集中 routing config(下階段)|

## 架構

```
┌──────────────────────────────────────────┐
│  orion-model-proxy(FastAPI, :9090)        │
│                                            │
│  POST /v1/messages          ← Orion native │
│  GET  /v1/models            ← merged catalog│
│  GET  /v1/health[/provider]                │
│                                            │
│  Backend: import orion_model              │
│  ├─ AnthropicProvider                     │
│  ├─ OpenAIProvider                        │
│  └─ OllamaProvider                        │
└──────────────────────────────────────────┘
                ▲ HTTPS(NDJSON streaming)
                │
  ┌─────────────┼─────────────┐
[CLI]      [Chat-api]    [Cowork sidecar]
  └─ import orion_model
     └─ get_provider() 偵測 ORION_MODEL_PROXY_URL
        ├─ 有 → HttpProxyProvider(走 proxy)
        └─ 無 → 直連對應 provider(舊行為)
```

## Wire format(Orion native)

**Request:**

```http
POST /v1/messages HTTP/1.1
Authorization: Bearer <ORION_MODEL_PROXY_KEY>   ← 可選
Content-Type: application/json

{
  "provider": "anthropic",
  "model": "claude-sonnet-4-6",
  "system": "...",
  "messages": [NormalizedMessage, ...],
  "tools": [ToolDefinition, ...] | null,
  "max_tokens": 4096,
  "temperature": 0.7 | null,
  "cache_breakpoints": [int, ...] | null,
  "reasoning_effort": "low" | "medium" | "high" | "minimal" | null
}
```

**Response:** `application/x-ndjson`,每行一個 `NormalizedEvent`:

```json
{"type":"message_start","message_id":"msg_...","model":"claude-haiku-4-5-..."}
{"type":"text_delta","text":"hello"}
{"type":"text_delta","text":" world"}
{"type":"tool_use_start","block_index":0,"tool_use_id":"toolu_...","tool_name":"Bash"}
{"type":"tool_use_input_delta","block_index":0,"partial_json":"{..."}
{"type":"tool_use_stop","block_index":0,"tool_use_id":"toolu_...","tool_name":"Bash","full_input":{...}}
{"type":"message_stop","stop_reason":"end_turn","usage":{...}}
```

**Why Orion native vs OpenAI-compat:**

- Anthropic thinking / cache_control / tool_use 各家有差,OpenAI-compat 翻譯有失真
- Wire = SDK 內部 `NormalizedEvent` JSON 化(全 Pydantic),host / proxy 兩邊
  反序列化即可,**沒中間翻譯層**
- 將來想對外公開 OpenAI-compat 介面是另開一條 endpoint,不衝突

## Quick start

### 1. 啟動 proxy

```bash
# Provider API keys 自己已有 .env / shell env
export ANTHROPIC_API_KEY=sk-ant-...
export OPENAI_API_KEY=sk-...
# 可選:proxy 自己的 auth token
export ORION_MODEL_PROXY_KEY=$(uuidgen)

# 起 proxy(default :9090)
uv run --package orion-model-proxy orion-model-proxy
# [orion-model-proxy] listening on http://127.0.0.1:9090(auth required)
```

可選 env vars:

| Env | 預設 | 說明 |
|---|---|---|
| `ORION_MODEL_PROXY_HOST` | `127.0.0.1` | listen host;對外服務改 `0.0.0.0` |
| `ORION_MODEL_PROXY_PORT` | `9090` | listen port |
| `ORION_MODEL_PROXY_KEY` | — | Bearer token;沒設 = 不認證(本機 dev) |

### 2. Host 切過去

```bash
# 三個 host 都一樣
export ORION_MODEL_PROXY_URL=http://127.0.0.1:9090
export ORION_MODEL_PROXY_KEY=<same as proxy>   # 若 proxy 有設

# 跑 CLI / Chat / Cowork — 程式碼不動,所有 LLM call 走 proxy
pnpm dev    # Cowork
uv run --package orion-chat-api uvicorn ...    # Chat
uv run --package orion-cli orion ...           # CLI
```

**驗證:**

```bash
# Proxy log 應該看到 POST /v1/messages 進來
# Host 那邊 conversation.stats / 對話一切正常
```

### 3. Fallback to direct

把 `ORION_MODEL_PROXY_URL` env unset,host 自動退回直連對應 provider — code 不動,
proxy 掛了也不會擋 host 工作。

## API

### `POST /v1/messages`

見上面 wire format。**Streaming only**(NDJSON),沒 blocking 模式。

### `GET /v1/models`

回 merged catalog(`orion_model.catalog.list_catalog()`):

```json
{
  "providers": [
    {"id": "anthropic", "label": "Anthropic", "models": [...]},
    {"id": "openai",    "label": "OpenAI",    "models": [...]},
    {"id": "ollama",    "label": "Ollama",    "models": [...]}
  ]
}
```

### `GET /v1/health` / `GET /v1/health/{provider}`

```json
GET /v1/health → {
  "ok": true,
  "providers": {"anthropic": true, "openai": true, "ollama": true}
}

GET /v1/health/anthropic → {"provider": "anthropic", "ok": true}
```

`ok=true` = 環境有 API key(沒實際 ping,避免每次 healthcheck 燒一次 token)。
Ollama 例外:會打 `/api/version` 真實 ping。

## Capabilities + cost — 本地算

`HttpProxyProvider.capabilities` / `estimate_cost()` 仍走 host 本地的
`orion_model.catalog` + `pricing` — 跟 proxy 用同一份 `models.json`,結果一致,
而且不必每次都打 proxy 問。

Proxy 那邊**也會**自己算一份(下階段做 budget enforcement / 使用統計用),
這份是 source of truth(host 端只是給 UI 顯示)。

## Phasing

**Phase A(本 commit)— MVP**
- ✅ FastAPI service + 3 endpoint
- ✅ NDJSON streaming wire(NormalizedEvent JSON 化)
- ✅ Bearer-token auth(optional)
- ✅ Host `HttpProxyProvider` + env gate
- ✅ Cowork / CLI / Chat zero code change

**Phase B(下階段)— Cost tracking**
- Postgres `proxy_usage`(per-user / per-model spend)
- Pre-call estimate + post-call 補真實 token
- Admin endpoint:`GET /v1/usage?user=...`

**Phase C — Routing**
- YAML config:`auto-fast`/`auto-deep` alias、per-user override
- Cowork model picker 多 `auto-*` 群組

**Phase D — Cache + audit log**
- sha256 cache layer(同 prompt+model → cached SSE,零 cost)
- audit log table(可選 full body / hash only / off)

**Phase E — Production polish**
- Failover(429 → 其他 provider)
- JWT auth(per-user identity)
- Rate limit、metrics、Grafana

## 已知限制

- **Proxy 是 SPOF** — 掛了所有 host 沒 LLM。緩解:env unset 立刻 fallback direct
- **多一跳延遲** — localhost <1 ms 可忽略;cross-net看網路。**Streaming first-chunk**
  晚 ~50 ms,token-throughput 不變
- **NDJSON 非標準** — OpenAI / Anthropic 用 SSE。但 NDJSON 更簡單(每行 JSON),
  client 端不必處理 `data:` prefix 或 keepalive。host 端 `httpx.AsyncClient`
  `aiter_lines()` 直接解
- **Ollama thinking field**:Ollama 把 reasoning 放新 `message.thinking` field
  而不在 `content`,`orion_model.ollama_provider` 還沒接(獨立 bug,跟 proxy 無關)

## 相關

- `packages/orion-model-proxy/`           Proxy service
- `packages/orion-model/src/orion_model/http_proxy_provider.py`  Host client
- `packages/orion-model/src/orion_model/provider.py:get_provider()`  env gate
