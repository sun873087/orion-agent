# Chat API

`apps/orion-chat/api/` — FastAPI + WebSocket + JWT auth server。把 `orion-sdk` 的能力對外暴露,給 web frontend / 行動裝置 / 第三方整合用。

**Entrypoint**:`orion-chat-api serve --host 0.0.0.0 --port 8000`(`src/orion_chat_api/cli.py`)

**App factory**:`src/orion_chat_api/app.py` 的 `create_app()`。

## 對外協定

| 路徑 | 協定 | 用途 |
|---|---|---|
| `POST /auth/register` `/auth/login` | REST | 註冊 / 登入,回 JWT |
| `GET /me` `/me/settings` `/me/memories` ... | REST | per-user 資源 CRUD |
| `GET /sessions` `POST /sessions` | REST | 對話 session 管理 |
| `GET /models` | REST | 可用 LLM model 列表 |
| `GET /healthz` | REST | health check |
| `WS /chat/stream/<session_id>?token=<jwt>` | WebSocket | 對話 streaming |
| `POST /uploads` `GET /uploads/<id>` | REST | 檔案上傳 |
| `*` (OAuth) | REST | OAuth callback flow(for MCP server OAuth) |

完整 schema 自動生成 → `apps/orion-chat/shared/openapi.json`(`scripts/dump_openapi.py`)。

## WebSocket protocol

`event_schema.py` 定義雙向訊息為 pydantic discriminated union:

### Client → Server(`ClientEvent`)

| `type` | 用途 |
|---|---|
| `user_message` | 使用者送 prompt |
| `permission_decision` | 對 PreToolUse ask 的回應 |
| `abort` | 中止當前 turn |

### Server → Client(`ServerEvent`)

| `type` | 用途 |
|---|---|
| `assistant_text_delta` | LLM streaming text |
| `assistant_thinking_delta` | LLM reasoning(若有) |
| `assistant_turn_complete` | 單 turn 結束 |
| `tool_use_start` | Tool 開始 |
| `tool_progress` | Tool 中繼進度 |
| `tool_result` | Tool 結果 |
| `permission_ask` | 要求 user 決定是否允許 tool |
| `loop_terminated` | 整個 query 結束 |
| `error` | 錯誤 |

Schema 自動生成 → `apps/orion-chat/shared/ws-{client,server}-events.schema.json`(`scripts/dump_ws_schema.py`),再 json2ts → web TS types。

## Auth 流程

1. `POST /auth/register` 或 `/auth/login` 拿到 `{access_token: "ey..."}`
2. REST 帶 `Authorization: Bearer ey...` header
3. WS 連線網址帶 `?token=ey...` query param(WebSocket 不支援 custom header,所以走 query string)
4. JWT subject(`sub`)是 `users.id` UUID(Phase 29 後),不是 username

bcrypt 雜湊密碼存 `users.password_hash`。Token TTL 預設 7 天,可透過 `ORION_JWT_TTL_SECONDS` 調。

## Session manager

兩種實作可選:

- `InMemorySessionManager` — 預設,程序重啟丟失對話。適合 dev / 單機。
- `DbSessionManager` — Postgres / SQLite,跨重啟保留。設 `ORION_DB_URL` 啟用。

每個 session 對應一個 `Conversation` instance,WS 連線時找出對應 session 灌進 manager。`session_manager_db.py` 用 SDK 的 `SessionStorage` 寫 JSONL transcript 跟 DB rows。

## Permission flow over WS

當 SDK 的 `can_use_tool` 走 `ask_via_websocket()`:

1. Server 送 `{"type": "permission_ask", "tool_name": "Bash", "tool_input": {...}}`
2. Web UI 顯示 dialog,user 選 allow / deny
3. Client 送 `{"type": "permission_decision", "tool_use_id": "...", "allow": true}`
4. SDK 收到後繼續 / 中止 tool 執行

實作:`ws_permissions.py` 用 asyncio.Future 串接 SDK callback 跟 WS 訊息往返。

## Multi-tenant

設 `ORION_DB_URL` 後,所有 user-scoped 資料(`users` / `sessions` / `user_settings` / `user_preferences` / `user_memories`)用 `user_id` FK 隔離。沒設則 in-memory + single-user 假設(本機 dev 模式)。

## CORS / CSRF

`app.py` middleware 設:

- CORS:`ORION_CORS_ORIGINS` env 控制白名單(逗號分隔)
- WS 沒有 CSRF(瀏覽器 Same-Origin Policy + JWT 已足夠)
- REST 用 Bearer token 不依賴 cookies → 沒 CSRF 問題

## 部署

`deploy/Dockerfile.api` multi-stage build,COPY `packages/orion-model` + `packages/orion-sdk` + `apps/orion-chat/api`,跑 `orion-chat-api serve`。

`deploy/docker-compose.yml` 含 Postgres + chat-api,本機 `docker compose up`。

Production K8s + Helm chart 設計見 [`../roadmap/plans/7c-helm-chart.md`](../roadmap/plans/7c-helm-chart.md)(未實作)。

## 設計取捨

- **REST + WS 並存而非單一協定** — 詳見 [`../architecture/design-decisions.md`](../architecture/design-decisions.md) §10
- **schema 從 pydantic 模型生** — 單一 source of truth,前後端契約對齊
- **JWT 不存 server-side state** — 水平擴展友善,但失去「強制登出單一裝置」能力(可接受 — Cowork / 行動 app 都是 long-lived token,不重要)

## 限制

- WS 沒有重連協議 — client 斷線後要自己重連並 replay state
- Permission ask 沒有 timeout — UI 不回應會卡住 tool 執行(可加 timeout,目前沒做)
- 沒有 rate limit middleware(由上游 nginx / API gateway 處理)

## 相關

- [agent-loop.md](./agent-loop.md) — SDK 那層的 event 流
- [web-frontend.md](./web-frontend.md) — chat/web 怎麼用本 API
- [`../guides/manual-testing.md`](../guides/manual-testing.md) — 手動驗證流程
