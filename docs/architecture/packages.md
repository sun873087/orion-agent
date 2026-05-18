# Packages

5 個 workspace member,各自獨立 `pyproject.toml` / `package.json`,共用 root `.venv` + `node_modules`。

---

## `packages/orion-model`

**LLM provider 抽象層**。Anthropic / OpenAI SDK 包裝成統一介面,輸出 normalized 事件流。

- 上游依賴:`anthropic`、`openai`、`httpx`、`pydantic`、`structlog`(Ollama 走 httpx,不用額外 SDK)
- 不依賴 agent loop / tools / DB / framework
- 適合單純做 prompt 測試、benchmark、純 chatbot

### 核心抽象

```python
from orion_model.provider import get_provider

provider = get_provider("anthropic", "claude-sonnet-4-6")
async for event in provider.stream(system=..., messages=..., tools=...):
    # event: TextDeltaEvent | ToolUseStartEvent | MessageStopEvent | ...
    ...
```

### 主要模組

| 檔案 | 內容 |
|---|---|
| `provider.py` | `LLMProvider` Protocol + `get_provider()` factory |
| `events.py` | `NormalizedEvent` union — 跨 provider 統一事件型別 |
| `types.py` | `NormalizedMessage` — 跨 provider 統一訊息型別 |
| `tool_def.py` | `ToolDefinition` — agent runtime 中立的 tool schema |
| `anthropic_provider.py` / `openai_provider.py` / `ollama_provider.py` | 三個實作(Phase 31-L 加 Ollama native — 走 `/api/chat` NDJSON streaming) |
| `translation/` | 各 provider 的 wire format ↔ Normalized 轉譯(`anthropic.py` / `openai.py` / `ollama.py`) |
| `catalog.py` + `models.json` | 已知模型表(context window、capabilities)— Ollama 標 `dynamic: true`,models list 空,靠 RPC `ollama.list_models` 動態抓 |
| `pricing.py` | per-token 計價(Ollama 永遠 $0) |
| `cache_config.py` | prompt caching 決策 |

---

## `packages/orion-sdk`

**Agent runtime SDK**。Conversation loop、tools、MCP、sandbox、memory、permission policy 等核心邏輯。

- 上游依賴:`orion-model` + `sqlalchemy` / `alembic` / `aiosqlite` / `asyncpg` / `mcp` / `docker` / `apscheduler` / `keyring` / `cryptography` / `nbformat` / `frontmatter` / `opentelemetry-*`
- **禁止依賴**:`typer`、`fastapi`、`uvicorn`、`click`(由 import-linter 強制)
- 不知道自己被誰用 — caller 可能是 CLI / chat-api / cowork sidecar / 第三方 app

### 核心進入點

```python
from orion_sdk.core.conversation import Conversation
from orion_sdk.core.state import AgentContext
from orion_sdk.tools.builtin_set import build_default_tool_set
from orion_model.provider import get_provider

llm = get_provider("anthropic", "claude-sonnet-4-6")
tools = build_default_tool_set(asker=None)  # asker 由 caller 注入
conv = Conversation(provider=llm, tools=tools)
ctx = AgentContext()

async for event in conv.send("讀 /etc/hosts", ctx=ctx):
    # event: AssistantTextDelta | ToolProgressUpdate | ToolResultUpdate | LoopTerminated
    ...
```

### 主要子目錄(22 個)

| 子目錄 | 內容 |
|---|---|
| `core/` | Conversation、QueryLoop、StreamingExecutor、ToolOrchestration — 心臟 |
| `tools/` | 20+ 共用內建工具(Bash / Read / Edit / Grep / WebFetch / Task / Skill / Schedule / Sleep / ToolSearch / ...);host-specific 不默認註冊:Browser → Cowork sidecar、Cron / Config → CLI |
| `mcp/` | MCP client(4 種 transport + OAuth + dynamic tool wrapping) |
| `sandbox/` | Docker / local sandbox backend |
| `permissions/` | Permission policy(`always_allow` / `ask` / DSL rules) |
| `prompt/` | System prompt assembler — 7 層靜態 + 動態段 + cache 決策 |
| `memory/` | per-user / per-project memory 載入 + 提取 |
| `state/` | `AgentContext`(每次 send 共用)、AppState |
| `storage/` | SQLAlchemy models + session 持久化 + 大結果三層 budget |
| `compact/` | 對話壓縮(auto / reactive / strategies / tombstone) |
| `recovery/` | ConversationRecovery — 中斷重啟 |
| `plan_mode/` | Plan mode 狀態機 |
| `multi_agent/` | Coordinator(leader-worker)+ Swarm(peer-to-peer)+ AgentSummary |
| `plugins/` `skills/` `hooks/` | 擴充機制(plugin / skill / 8 種 hook event) |
| `output_styles/` | 輸出樣板 |
| `telemetry/` | OpenTelemetry instrumentation + cost tracker |
| `perf/` | pyinstrument profiling |
| `services/` | feature_flags、forked_agent、side_query |
| `migrations/` | alembic 設定 + revision 檔(誰用 DB 誰跑) |

---

## `apps/orion-cli`

**Terminal CLI**。Typer-based,stdin / stdout / TTY 互動,用 `orion-sdk` 跑 agent loop。

- 上游依賴:`orion-sdk` + `typer` + `python-dotenv`
- Entrypoint:`orion`(`pyproject.toml [project.scripts]`)

### 命令

| 命令 | 用途 |
|---|---|
| `orion run "<prompt>"` | 跑一次 agent loop |
| `orion run --resume <session-id>` | 從先前 session 繼續 |
| `orion run --no-memory --no-mcp --sandbox docker ...` | 各種 flag |

`serve`(原 chat-api 入口)**已移到 `orion-chat-api`**。

### 子目錄

| 子目錄 | 內容 |
|---|---|
| `commands/` | Slash 命令(`/clear` `/help` `/model` 等)註冊與分發 |
| `input/` | stdin 處理 + slash parser + image upload + token estimation |
| `cron_tools/` | `CronCreate / CronList / CronDelete`(APScheduler-backed shell cron)— Phase 31-H 從 SDK 搬來,CLI-only |
| `config_tool.py` | `Config` LLM tool(讀寫 `~/.orion/settings.json`)— Phase 31-I 從 SDK 搬來,CLI-only |
| `__main__.py` | `orion` entrypoint(typer app) |

---

## `apps/orion-chat/api`

**FastAPI + WebSocket + JWT auth server**。對外提供 `orion-sdk` 的能力給遠端 client(web / 行動裝置)。

- 上游依賴:`orion-sdk` + `fastapi` + `uvicorn[standard]` + `pyjwt` + `bcrypt` + `typer`
- Entrypoint:`orion-chat-api serve --host 0.0.0.0 --port 8000`

### 主要模組

| 檔案 | 內容 |
|---|---|
| `app.py` | FastAPI app + middleware + 啟動 hook |
| `cli.py` | `orion-chat-api serve` typer entry |
| `auth.py` / `auth_db.py` | JWT 簽發 + bcrypt + user DB(`users` 表) |
| `deps.py` | `current_user` 等依賴注入 |
| `event_schema.py` | WS `ClientEvent` / `ServerEvent` pydantic discriminated unions |
| `session_manager.py` / `session_manager_db.py` | in-memory + DB-backed 對話 manager |
| `ws_permissions.py` | WS 上的 permission ask flow |
| `routes/` | REST endpoints:auth / sessions / me / settings / memories / models / health |

### 與 orion-chat/web 的契約

- REST schema 自動生成:`apps/orion-chat/shared/openapi.json` ← `scripts/dump_openapi.py`
- WS schema 自動生成:`shared/ws-{client,server}-events.schema.json` ← `scripts/dump_ws_schema.py`
- TS types 自動生成:`web/src/types/*.gen.ts` ← `npm run gen:ts-types`

---

## `apps/orion-chat/web`

**Vite + React + TypeScript 客戶端**(@orion/chat-web)。

- npm workspace member,scoped name `@orion/chat-web`
- 上游依賴:`react`、`react-dom`、`react-markdown`、`remark-gfm`、`zustand`
- 開發:`npm run dev -w @orion/chat-web`(vite :5173,proxy 到 chat-api :8000)
- Build:`npm run build -w @orion/chat-web`(vite + tsc)

### 主要目錄

| 目錄 | 內容 |
|---|---|
| `src/api/` | `apiFetch` / `apiUpload`(REST client) + `auth` 工具 |
| `src/components/` | ChatView / MessageList / InputBox / 各 panel |
| `src/hooks/` | useSessions / useModelCatalog 等 |
| `src/types/*.gen.ts` | OpenAPI / WS schema 生成的 TS 型別(**不要手改**) |
| `src/lib/` | WebSocket client、訊息序列化 |

---

## `apps/orion-cowork`

**PC 桌機 app**(@orion/cowork)— Electron + React renderer + Python sidecar 三層。

**不經過 chat-api** — sidecar 直接 `import orion_sdk` 跑 agent loop,跟 cli / chat-api 是平行的 SDK consumer。

### 三層

```
Renderer (React, 獨立重寫) ◀── IPC ──▶ Main (Electron Node TS) ◀── stdio JSON-RPC ──▶ Sidecar (Python)
```

| 子目錄 | 內容 |
|---|---|
| `package.json` | `@orion/cowork`(Electron + Vite + React) |
| `electron/` | main process (TS, CommonJS):`main.ts` / `sidecar.ts` / `preload.ts` |
| `renderer/` | React UI(獨立重寫,**不**複用 chat/web)+ `agent.ts` (window.agent.call wrapper) |
| `sidecar/` | Python workspace member `orion-cowork-sidecar`:`rpc.py` / `handlers.py` / `streaming.py` / `desktop_tools.py`(OpenUrl / OpenPath)/ `browser_tools/`(Phase 31-H 從 SDK 搬來,Cowork-only,headful Chrome via playwright) |

### 為何不走 chat-api

Cowork 是本機單機 app — 不需要 JWT / CORS / 多 session / HTTP overhead。Sidecar 直接跑 SDK,stdio 通訊,沒有 server port 對外。

詳見 [`design-decisions.md`](./design-decisions.md)。

---

## 速查表

| Package | 語言 | 大小(LOC 級) | Entrypoint | 用途 |
|---|---|---|---|---|
| `orion-model` | Python | ~600 | (lib) | LLM 抽象 |
| `orion-sdk` | Python | ~15k | (lib) | Agent runtime |
| `orion-cli` | Python | ~1k | `orion` | Terminal CLI |
| `orion-chat-api` | Python | ~2k | `orion-chat-api serve` | REST + WS server |
| `orion-chat/web` | TypeScript | ~3k | `npm run dev` | Web 客戶端 |
| `orion-cowork` | TS + Python | ~1k | `npm run dev -w @orion/cowork` | 桌機 app |
