# Packages

3 個 reusable lib package + 3 個 app。本文掃過每一個 — 一句話定位、實作位置、
entrypoint。

## packages/

### orion-model

純 LLM provider 抽象 — 只負責「拿到 prompt → 回 stream of events」。**不認** agent
loop、不認工具、不認 memory。Cowork / CLI / Chat / proxy 都 import 它。

```
packages/orion-model/src/orion_model/
├── provider.py                  通用 Provider 介面 + factory
├── anthropic_provider.py        AsyncAnthropic SDK 薄包
├── openai_provider.py           AsyncOpenAI SDK 薄包(Responses API)
├── ollama_provider.py           本機 daemon HTTP
├── openrouter_provider.py       OpenRouter gateway(OpenAI-compat chat.completions wire)
├── google_provider.py           Google Gemini(native /v1beta API + thought_signature)
├── events.py                    NormalizedEvent / NormalizedUsage(跨 provider 一致)
├── types.py                     NormalizedMessage / ImageBlock / TextBlock(含 ToolUseBlock.thought_signature)
├── errors.py                    ProviderHTTPError — native http provider 4xx/5xx 友善訊息
├── catalog.py + models.json     Chat model catalog(pricing / max_tokens;packaged static)
├── stt_catalog.py + stt_models.json    STT pricing
├── tts_catalog.py + tts_models.json    TTS pricing
├── pricing.py                   token → USD 計算
├── cache_config.py              Anthropic cache TTL
├── translation/                 NormalizedMessage ↔ provider 各自格式
└── audio/                       STT / TTS direct calls
    ├── stt.py
    └── tts.py
```

**對外 entry**:`from orion_model.provider import get_provider("anthropic", "claude-...")`
;`from orion_model.audio import transcribe, synthesize`。

**OpenRouter**(gateway 模式)— 一支 `OPENROUTER_API_KEY` 接 100+ models 來自各
vendor。`OpenRouterProvider` 走 chat.completions wire(不是 OpenAI Responses API)。
Models 寫進 `models.json` static section(精選 :free tier 等),user 想加新 model
直接編 JSON。

**Google Gemini** — 走 native Gemini API
(`generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse`)
而**非** OpenAI-compat 端點。原因:multi-turn tool use 需要 `thought_signature`
跨 turn echo,OpenAI-compat 不傳這欄位會 400。Native API 我們完整管 signature ——
`stream()` 從 functionCall part 抽 `thoughtSignature`,塞進 `ToolUseBlock.thought_signature`,
下個 turn 翻譯回 Gemini 時放回 `parts[].thoughtSignature`。Translation 在
`google_provider` 內自己一套(NormalizedMessage ↔ contents/parts),schema cleaner
做 `$ref` inline + 砍 `exclusiveMinimum` / empty enum 等 Gemini 不認的 keyword。
Auth 直連用 `x-goog-api-key`,proxy 用 Bearer。Proxy 模式:client
`base_url={proxy}/google/v1beta`,proxy `upstream_base=generativelanguage.googleapis.com`。

**ProviderHTTPError**(`errors.py`)— Native httpx provider(目前 google,將來別的)
4xx/5xx 不裸 raise `httpx.HTTPStatusError`,改 raise `ProviderHTTPError` 帶
`status_code` / `provider` / `upstream_message`,`__str__` 自動組中文友善訊息
(429 Gemini 給 free tier 配額 hint、400 帶 upstream validation message 等)。
Sidecar `_format_send_error` 識別後直接給 UI,不爆 raw JSON。SDK-based provider
(openai / anthropic)用 SDK 自家 `RateLimitError` / `AuthenticationError`,既有
mapping 已認 — 不用這 class。

### orion-sdk

Agent runtime — agent loop + 工具 + 權限 + 記憶 + MCP + skills + sandbox + ...。
host(CLI / chat-api / sidecar)透過 callback 注入「session 怎麼存 / 工具怎麼跑」,
SDK 只定義 spec。

```
packages/orion-sdk/src/orion_sdk/
├── core/
│   ├── conversation.py          Conversation(state machine + send loop)
│   ├── query_loop.py            QueryLoop(provider stream → 高層 event)
│   ├── streaming.py             ExecutorPolicy → 平行 tool 執行
│   └── state.py                 AgentContext(turn-level mutable state)
├── tools/                       30+ builtin + ToolDefinition spec
│   ├── builtin_set.py           build_default_tool_set(callbacks)
│   ├── file/                    Read / Write / Edit / Glob / Grep
│   ├── shell/                   Bash / sandbox
│   ├── web/                     WebFetch / WebSearch
│   ├── agent/                   AgentTool(sub-agent spawn)
│   ├── special/                 ExitPlanMode / TodoWrite / ask_user_question
│   └── ...
├── permissions/                 PermissionPolicy(always_allow / ask / DSL)
├── memory/                      Per-user / per-project markdown memory
├── compact/                     對話自動壓縮(token-based + reactive)
├── mcp/                         MCP server lifecycle(stdio / SSE / http / WS / OAuth)
├── skills/                      Skill bundle loader(markdown + frontmatter)
├── plugins/                     Third-party extension entry point
├── hooks/                       8 種 hook event(SessionStart / PreToolUse / ...)
├── multi_agent/                 Coordinator(leader-worker)+ Swarm(peer)
├── sandbox/                     Docker / local 沙箱
├── recovery/                    Resume from snapshot
├── storage/                     SQLAlchemy session DB(SQLite / Postgres)
├── services/                    Feature flags / shared utilities
└── plan_mode/                   Read-only investigation mode + 計畫審核
```

**對外 entry**:`from orion_sdk.core.conversation import Conversation`(主要)。

### orion-model-proxy

HTTP service 包 OpenAI / Anthropic — transparent reverse proxy(byte-for-byte 透傳)+
multi-tenant auth + per-user cost tracking + budget enforcement + admin Web UI。
**opt-in**:host 不必走它,直接打 upstream 也行(env-gated)。

```
packages/orion-model-proxy/src/orion_model_proxy/
├── server.py                    FastAPI app + lifespan + WS skeleton
├── __main__.py                  uvicorn entrypoint
├── db.py                        SQLAlchemy async engine + auto-migration
├── models.py                    ORM:User / ApiKey / UsageLog / AuditLog /
│                                Organization / RoutingAlias / PromptCache /
│                                Webhook / UsageMonthlyRollup
├── auth.py                      sha256 Bearer lookup + cache + budget / rate enforce
├── upstream_proxy.py            tee response → parser + log usage
├── usage_parser.py              per-endpoint usage 解析(chat / responses /
│                                embeddings / messages / audio.speech)
├── usage_logger.py              DB insert(fire-and-forget)+ running cost cache
├── rate_limit.py                Token bucket(per-user RPM)
├── archive.py                   >cutoff_days usage_log → monthly rollup
├── backup.py                    JSON-zip 全表 dump/restore(跨 SQLite/PG)
├── audit.py                     Admin action audit recorder
├── telemetry.py                 OTel span(env-gated, lazy import)
├── webhook.py                   budget threshold POST
├── routing.py                   user-level model alias 解析
├── cache.py                     Content-hash prompt cache(skip stream/tools)
├── failover.py                  provider fallback chain skeleton
├── admin_routes.py              /admin/* REST(users / keys / org / webhook / ...)
├── admin_ui.py                  /admin/ui/* Jinja2 server-rendered
└── templates/                   base / login / users / user_detail / audit HTML
```

**對外 entry**:`make dev-model-proxy` 或 `uv run --package orion-model-proxy orion-model-proxy`。
Client 端只需設 env `ORION_MODEL_PROXY_URL=http://...` + `ORION_MODEL_PROXY_KEY=sk-orion-...`。

## apps/

### orion-cli

終端機 chat。最簡單,單檔 entrypoint。

```
apps/orion-cli/
├── src/orion_cli/
│   ├── __main__.py              Typer CLI:orion run "..." / orion chat / ...
│   ├── slash/                   Slash command handlers
│   ├── commands/                Builtin slash 實作
│   └── output_styles/           Plain / Markdown / JSON / ...
└── tests/                       Unit + integration(gated on env)
```

Sessions 走 `~/.orion/sessions/<uuid>/transcript.jsonl`(per-session 子目錄)。

### orion-chat

Web-facing FastAPI server + Vite React 客戶端。Multi-tenant 設計,JWT auth,Postgres-ready。

```
apps/orion-chat/
├── api/                         FastAPI server
│   ├── src/orion_chat_api/
│   │   ├── app.py               FastAPI app + lifespan + CORS
│   │   ├── cli.py               orion-chat-api serve(uvicorn entrypoint)
│   │   ├── routes/              auth / chat / models / sessions / oauth / ...
│   │   ├── auth/                JWT + OAuth providers(github / linear / google / microsoft)
│   │   ├── deps.py              FastAPI Depends 工廠
│   │   └── db.py                Async SQLAlchemy
│   └── tests/
└── web/                         Vite + React + Tailwind
    └── src/
        ├── App.tsx
        ├── api/                 fetch wrappers + WebSocket client
        ├── components/          Sidebar / Chat / Settings / ...
        └── store/               Zustand state
```

Sessions 走 `~/.orion/sessions/<uuid>/`(同 CLI)或 Postgres(production)。

### orion-cowork

Electron 桌機 chat app — Python sidecar(用 orion-sdk)+ React renderer + Electron main。

```
apps/orion-cowork/
├── electron/                    main process + preload
│   ├── main.ts                  BrowserWindow + IPC + sidecar lifecycle + auto-update
│   ├── preload.ts               contextBridge 暴露 window.{agent,dialog,scheduler,...}Api
│   ├── sidecar.ts               Python sidecar spawn + stdio JSON-RPC
│   └── updater.ts               electron-updater wire
├── renderer/                    React UI
│   ├── src/
│   │   ├── App.tsx
│   │   ├── components/          InputBox / MessageList / Sidebar / Header / ...
│   │   ├── store/               Zustand(agent / settings / projects)
│   │   ├── api/                 JSON-RPC wrappers
│   │   └── i18n/                4 locale(zh-TW / zh-CN / en / ja)
│   └── public/
├── sidecar/                     Python — uses orion_sdk
│   ├── src/orion_cowork_sidecar/
│   │   ├── __main__.py          uv run entrypoint
│   │   ├── handlers.py          所有 RPC method(conversation / project / memory / ...)
│   │   ├── rpc.py               stdio JSON-RPC server
│   │   ├── storage.py           SQLite engine(cowork.db extends SDK schema)
│   │   ├── backup_handlers.py   Cowork data zip backup/restore
│   │   ├── stt_handlers.py / tts_handlers.py
│   │   ├── scheduler.py         /loop schedule + cron
│   │   ├── mcp_integration.py   Cowork-side MCP wiring
│   │   └── desktop_tools.py     OpenPath / OpenUrl(本機 desktop 專屬)
│   └── tests/
├── electron-builder.yml         DMG / NSIS / AppImage + signing config
└── package.json                 Electron / Vite / pnpm workspace
```

Sessions 走 `~/.orion/sessions/cowork.db`(SQLite,跟 SDK 共用 messages/sessions 表 +
`cowork_*` 擴充表)。Cowork sidecar 不走 chat-api — 本機單機不需要 HTTP / JWT。

## 看完繼續

- [runtime-layout.md](./runtime-layout.md) — 設定 / 資料在哪幾個目錄
- [design-decisions.md](./design-decisions.md) — 為何這樣不那樣
- [`../features/`](../features/) — 各 feature 怎麼運作
