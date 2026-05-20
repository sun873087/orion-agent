# Model Proxy

Transparent reverse proxy 包 OpenAI / Anthropic,加 multi-tenant auth + per-user
計費 + budget enforcement + admin Web UI。可選 service,不啟用 client 直連也行。

**實作位置**:`packages/orion-model-proxy/`

## 為什麼存在

| 痛點 | Proxy 解什麼 |
|---|---|
| `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` 散在各 host `.env` | 集中於 proxy 那台機,client 不需要真 key |
| Cost 各 host 各算,看不到全貌 | proxy 內 `usage_log` 表 + admin dashboard |
| 想限 user 用量 / 月預算 | per-user budget cap + rate limit(RPM) |
| 多人用同 API key 沒法歸帳 | 每位 user 一個 sk-orion-... token,usage_log 帶 user_id + client_id |
| 想 routing alias / cache / failover | 集中加在 proxy(opt-in) |
| 外部 SDK / 工具(LangChain / aider / Cursor)想共用 key | 它們 `base_url` 設 proxy 直接 work |

## 架構

```
┌─────────────────────────────────────────────────────────────────┐
│  orion-model-proxy(FastAPI, :9090)                               │
│                                                                  │
│  /openai/{path:path}     → api.openai.com    catch-all,透傳     │
│  /anthropic/{path:path}  → api.anthropic.com 同上,5 verb 全收  │
│  /v1/health[/{provider}]                       public,no auth   │
│  /v1/catalog                                   chat/stt/tts JSON │
│  /admin/*                                      REST(admin token) │
│  /admin/ui/*                                   Jinja2 web UI     │
│                                                                  │
│  request:                                                        │
│    ① require_auth — sha256(Bearer) → DB lookup → principal      │
│    ② enforce_rate_limit — token bucket(RPM)                     │
│    ③ enforce_budget — running_cost >= cap → 402                 │
│    ④ 改寫 Authorization / x-api-key 為 server-side 真 key        │
│    ⑤ forward upstream                                           │
│                                                                  │
│  response:                                                       │
│    ⑥ tee bytes → client + parser                                │
│    ⑦ stream 結束 → parse usage → log + incr running cost         │
│    ⑧ budget 達 80% / 100% → webhook fire(若有設)               │
└─────────────────────────────────────────────────────────────────┘
                ▲                                  │
                │ OpenAI / Anthropic 原生 wire     │ tee 解析 + 寫 DB
                │                                  ▼
   ┌────────────┼─────────────────────────────┐   ┌─────────────┐
   │            │                             │   │  proxy.db   │
[自家 host]                              [外部 SDK]    │  (SQLite /  │
 import orion_model                       LangChain    │   Postgres) │
   provider.get_provider("anthropic"...)  / aider /    └─────────────┘
   audio.transcribe(...) / synthesize(...)curl / 等
   ↑
   SDK base_url 由 env ORION_MODEL_PROXY_URL 控:
     有設 → AsyncAnthropic(base_url=f"{proxy}/anthropic")
            AsyncOpenAI(base_url=f"{proxy}/openai/v1")
     沒設 → SDK 預設打 api.{anthropic,openai}.com
   Ollama 不經 proxy(本機 daemon,無 key 概念,proxy 無增值)
```

## DB Schema

```sql
users (id, email, display_name, budget_usd, rate_limit_rpm, organization_id, created_at)
api_keys (id, user_id, token_hash, token_prefix, label, created_at, last_used_at, revoked_at)
usage_log (id, user_id, api_key_id, provider, model, endpoint,
           input/output/cache_read/cache_creation_tokens, cost_usd, ts,
           client_id, request_id)
audit_log (id, ts, action, target_type, target_id, detail)         -- admin action 留底
organizations (id, name, monthly_budget_usd, created_at)            -- multi-org 預留
routing_aliases (id, user_id, alias, target_provider, target_model) -- "auto-fast" → 真實 model
prompt_cache (id, content_hash, provider, model, response_blob,
              created_at, hit_count)                                 -- prompt cache layer
webhooks (id, user_id, event, url, enabled, created_at)             -- budget threshold POST
usage_monthly (id, user_id, year_month, provider, model,
               total_input_tokens, total_output_tokens,
               total_cost_usd, request_count)                       -- >90 天 archive
```

DB backend 由 `ORION_PROXY_DB_URL` env 切:dev 用 SQLite,prod 用 Postgres。`init_db()`
自動 `create_all` + 用 inspector 補缺 column(輕量 migration)。

## Quick start

```bash
# 1. Bootstrap(一鍵生 ADMIN_KEY + 寫 .env + 指引)
make proxy-bootstrap

# 2. 填上游 key
$EDITOR packages/orion-model-proxy/.env
# ANTHROPIC_API_KEY=sk-ant-...
# OPENAI_API_KEY=sk-proj-...

# 3. 跑 proxy
make dev-model-proxy
# [orion-model-proxy] listening on http://127.0.0.1:9090  (admin endpoints: enabled)

# 4. Admin UI 建 user + 生 token
open http://127.0.0.1:9090/admin/ui/
# Login(貼 admin token)→ New user → Generate API key → 複製明文

# 5. Client 端用那 token
# apps/orion-cowork/.env
ORION_MODEL_PROXY_URL=http://127.0.0.1:9090
ORION_MODEL_PROXY_KEY=sk-orion-prod-...
```

## Auth 三層 token(Phase 32 起 multi-tenant only)

| Token | 設在哪 | 用途 |
|---|---|---|
| `ORION_MODEL_PROXY_ADMIN_KEY` | proxy server env | 進 `/admin/*` REST + `/admin/ui` |
| User API key(`sk-orion-<env>-<random>`) | proxy DB(`api_keys.token_hash`) | client 走 `/openai/*` `/anthropic/*` 帶這個 |
| `ANTHROPIC_API_KEY` / `OPENAI_API_KEY` | proxy server env | proxy 對上游用真實 key |

Status code 對齊 OpenAI / Anthropic 慣例:

| 情境 | Status |
|---|---|
| 沒帶 token / 格式錯 / DB 找不到 | **401** Unauthorized(SDK AuthenticationError) |
| Token 曾有但被 revoked | **403** Forbidden(SDK PermissionDeniedError) |
| Budget cap 已達 | **402** Payment Required |
| Rate limit 超 | **429** Too Many Requests |
| Upstream provider key 未設 | 503 |

## Per-endpoint 計費

`usage_parser.py` 對下列 endpoint 做 token 提取 + cost 計算:

| Endpoint | 提取邏輯 |
|---|---|
| `/openai/v1/chat/completions`(stream + non-stream) | `usage.prompt/completion_tokens` + `prompt_tokens_details.cached_tokens` |
| `/openai/v1/responses` | `usage.input/output_tokens` |
| `/openai/v1/embeddings` | `usage.prompt_tokens` |
| `/openai/v1/audio/speech` | `input` text 字元數 × tts pricing |
| `/anthropic/v1/messages`(stream + non-stream) | `usage.input/output/cache_read/cache_creation_input_tokens` |
| 其他 | log endpoint + cost=0(best-effort) |

Pricing 來源:`orion_model.catalog` / `tts_catalog`(跟 client SDK 同份)。

## Admin features

### Web UI(`/admin/ui/`)
- Login(HttpOnly cookie 8h session)
- Users list + 月用量 sparkline
- User detail:keys 列表 / generate / rotate / revoke / budget / 30-day chart
- Audit log
- Dark mode toggle(localStorage)

### REST
- `/admin/users` CRUD + `/keys` + `/budget` + `/rate_limit` + `/usage` + `/usage/daily`
- `/admin/keys/{id}/rotate` — atomic 新 key + revoke 舊
- `/admin/organizations` + `/admin/routing_aliases` + `/admin/webhooks`
- `/admin/audit` — 最近 N 筆 admin action
- `/admin/maintenance/archive` — usage_log 90+ 天歸檔 → monthly rollup
- `/admin/maintenance/backup` + `/restore` — 全表 JSON-zip dump

## 行為:外部 SDK 用法

**Python OpenAI SDK**:

```python
from openai import OpenAI
client = OpenAI(
    base_url="http://proxy.local:9090/openai/v1",
    api_key="sk-orion-prod-...",  # admin 給的
)
# Chat / Responses / Embeddings / TTS / STT / Files / 任何 endpoint 自動支援
resp = client.chat.completions.create(model="gpt-5-mini", messages=[...])
```

**Python Anthropic SDK**:

```python
from anthropic import Anthropic
client = Anthropic(
    base_url="http://proxy.local:9090/anthropic",
    api_key="sk-orion-prod-...",
)
resp = client.messages.create(model="claude-haiku-4-5", ...)
```

**curl**:

```bash
curl http://proxy.local:9090/openai/v1/chat/completions \
  -H "Authorization: Bearer sk-orion-prod-..." \
  -H "Content-Type: application/json" \
  -d '{"model":"gpt-5-mini","messages":[{"role":"user","content":"hi"}]}'
```

## Webhook(budget threshold)

`webhook` 表內配置:

```bash
curl -X POST http://proxy:9090/admin/webhooks \
  -H "Authorization: Bearer $ADMIN_KEY" \
  -d '{"event":"budget.exceeded","url":"https://hooks.slack.com/services/..."}'
```

Events:
- `budget.warning_80` — user 累積 cost 達 cap × 80%
- `budget.exceeded` — 達 100%(per user per event 只 fire 一次,reset 在 set_budget 時)
- `key.revoked` / `user.created`(待接)

Payload:

```json
{
  "event": "budget.exceeded",
  "ts": 1700000000,
  "user_id": "...",
  "user_email": "alice@example.com",
  "data": { "running_cost": 50.1, "budget_cap": 50.0, "pct": 1.002 }
}
```

## Backup / Restore

```bash
# Export(全表 JSON-zip,跨 SQLite/PG)
curl -X POST "http://proxy:9090/admin/maintenance/backup?target_path=/tmp/proxy.zip" \
  -H "Authorization: Bearer $ADMIN_KEY"

# Restore(replace_all=true 預設,truncate 全表 + insert)
curl -X POST "http://proxy:9090/admin/maintenance/restore?source_path=/tmp/proxy.zip" \
  -H "Authorization: Bearer $ADMIN_KEY"
```

## 限制 / 已知問題

- **Hard budget last-request 略過 cap**:Pre-request 不知這次會花多少,只能擋下一次。文件明寫,user 接受。
- **Single-process rate limit**:in-memory token bucket,多 instance 不共用。Production 要 Redis-backed。
- **WebSocket realtime 還 skeleton**:`/openai/v1/realtime` endpoint 註冊但回 503 — Voice realtime 不通。
- **Streaming 大檔上傳**:`req.body()` 整個讀進 memory,GB 級 fine-tuning training file 會爆 RAM。要 streaming request body。
- **Prompt cache 沒 TTL eviction**:目前 hash 命中就回,沒 expire 機制。長跑會無限增。
- **Failover skeleton**:`failover.py` 有 fallback chain 跟 status check,但 reverse proxy 還沒接入(需跨 provider wire format 互轉)。

## 看完繼續

- [`../architecture/design-decisions.md`](../architecture/design-decisions.md) — 為何 transparent reverse + 為何 multi-tenant
- [models.md](./models.md) — 直連模式的 provider 行為
- [`../roadmap/README.md`](../roadmap/README.md) — Proxy 還在做什麼(routing 接入 / WS / cache eviction)
