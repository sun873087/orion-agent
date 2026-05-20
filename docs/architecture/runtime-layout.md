# Runtime layout — orion-agent 的 config / data 在哪

Source code 結構見 [`packages.md`](./packages.md)。本文講 **runtime** 設定 / 資料散落
的位置。

## 哲學

**所有 host 共用 `~/.orion/` root**。skills / memory / mcp.json / users 共用(一邊裝兩邊都看見);
sessions 透過子目錄 + 不同檔名隔離:

```
~/.orion/
├── skills/                          ✅ system skills(共用 across hosts)
├── users/<user_id>/
│   ├── skills/                      ✅ per-user skills
│   ├── memory/                      ✅ per-user markdown memory
│   └── workspace/                   ✅ Cowork 對話工作目錄
├── mcp.json                         ✅ Global MCP servers(共用)
├── settings.json                    ✅ CLI / chat-api 設定(Cowork 不用)
├── permissions.json                 ✅ Global permission rules(共用)
├── sessions/
│   ├── cowork.db                    Cowork SQLite(`cowork_*` 擴充表 + SDK 共用表)
│   ├── cli.db                       CLI 用 SQLite(可選 — 預設 JSONL)
│   └── <uuid>/                      CLI / chat-api JSONL pattern(per-session dir)
│       └── transcript.jsonl
├── blobs/                           ✅ Content-hash blob store(Cowork attachment + CLI 共用)
├── tts-cache/                       ✅ TTS audio cache(SHA256 / 用 hash 去重)
└── plans/                           Plan mode 計畫檔
```

各路徑由 `data_dir()` 函式回。`ORION_COWORK_DATA_DIR` env 可 override(e2e 測試用)。

## Per-app .env

Phase 32 起,每個 app / package 用自己的 `.env`(不共用 root):

```
apps/orion-cli/.env                              ← CLI app(provider key 或 PROXY_URL)
apps/orion-chat/.env                             ← chat-api(+ DB / JWT / OAuth)
apps/orion-cowork/.env                           ← Cowork(provider key 或 PROXY_URL)
packages/orion-model-proxy/.env                  ← proxy server 自己(upstream key + ADMIN_KEY)
```

各自的 `.env.example` 是該 role 看得到的 env 完整清單。複製成 `.env` 填值:

```bash
cp apps/orion-cli/.env.example apps/orion-cli/.env
cp apps/orion-chat/.env.example apps/orion-chat/.env
cp apps/orion-cowork/.env.example apps/orion-cowork/.env
cp packages/orion-model-proxy/.env.example packages/orion-model-proxy/.env
```

## Client 端常見 env

```bash
# 1. Provider keys — 直連時用
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...
OLLAMA_HOST=localhost:11434

# 2. Model proxy — 設了就走 proxy(集中計費 / 限速)
ORION_MODEL_PROXY_URL=http://127.0.0.1:9090
ORION_MODEL_PROXY_KEY=sk-orion-prod-...      # admin 在 /admin/ui 為你生成
ORION_CLIENT_ID=orion-cli                    # 預設 entrypoint 自己 setdefault

# 3. 行為調校
ORION_MAX_TOKENS_PER_TURN=32768
ORION_CACHE_TTL_STATIC=1h
ORION_CACHE_TTL_SESSION=1h
ORION_CACHE_TTL_MESSAGES=5m
ORION_WEBFETCH_TTL_SECONDS=300
ORION_FILE_HISTORY_MAX_SNAPSHOTS=100
ORION_MEMORY_RANKER=heuristic                # heuristic / llm
ORION_MEMORY_RANKER_MODEL=claude-haiku-4-5
SERPAPI_API_KEY=...                          # WebSearch tool

# 4. Token storage
ORION_DISABLE_KEYCHAIN=1                     # Linux server / Docker 用
ORION_MASTER_KEY=<fernet-key>                # 生產用,從 secrets manager 注入

# 5. Chat-api(production)
ORION_DB_URL=postgresql+asyncpg://user:pass@host/orion
ORION_JWT_SECRET=<random-long-string>
ORION_CORS_ORIGINS=https://chat.example.com
GITHUB_OAUTH_CLIENT_ID=... / SECRET=...     # OAuth providers
```

## Proxy server 端 env

```bash
# Listen
ORION_MODEL_PROXY_HOST=127.0.0.1               # 對外服改 0.0.0.0
ORION_MODEL_PROXY_PORT=9090

# Admin Bearer — 沒設 admin endpoints 全 503
ORION_MODEL_PROXY_ADMIN_KEY=<random-32-bytes>

# DB(SQLite for dev / Postgres for prod)
ORION_PROXY_DB_URL=sqlite+aiosqlite:///./proxy.db
# 或:postgresql+asyncpg://orion:pass@db.internal/orion_proxy

# Upstream provider keys(proxy 用真 key 覆寫 client 帶的)
ANTHROPIC_API_KEY=sk-ant-...
OPENAI_API_KEY=sk-proj-...

# Observability(opt-in)
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.internal/v1/traces
```

Phase 31-X 的單一 `ORION_MODEL_PROXY_KEY` server-side env mode 已**移除** — 改成
multi-tenant 唯一模式,token 由 admin 透過 `/admin/ui` 為每位 user 個別生成。

## Dispatch 邏輯

Host 怎麼決定打哪:

```
1. Test override(set_test_provider_factory)→ Mock provider(e2e)
2. ORION_MODEL_PROXY_URL 設了 → SDK base_url = proxy(透傳 + 計費)
3. 否則 → 直連 api.{anthropic,openai}.com / localhost:11434
```

`orion_model.provider.get_provider("anthropic", "claude-...")` 內部判斷,host code 不必管。

## 看完繼續

- [packages.md](./packages.md) — source code 在哪
- [design-decisions.md](./design-decisions.md) — 為何 4 個 .env 各自隔離
- [`../features/model-proxy.md`](../features/model-proxy.md) — proxy 行為細節
