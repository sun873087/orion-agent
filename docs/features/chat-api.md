# Chat API

`apps/orion-chat/api/` — FastAPI + WebSocket + JWT auth server。把 `orion-sdk` 的能力對外
暴露,給 web frontend / 行動裝置 / 第三方整合用。

**實作位置**:`apps/orion-chat/api/src/orion_chat_api/`

## 行為

- **HTTP REST**:`POST /chat/sessions` / `GET /chat/sessions/{id}/messages` / ...
- **WebSocket**:`/ws/chat?session_id=...` — 雙向 stream(send msg + receive event)
- **JWT auth**:`POST /auth/login` 拿 token,後續 request `Authorization: Bearer`
- **OAuth providers**(opt-in env):GitHub / Linear / Google / Microsoft — 跑 OAuth callback,把 token 存 keychain 給 MCP server 用
- **Models endpoint**:`GET /models` 回 catalog(web 顯下拉)
- **CORS 預設 `*`**(dev),`ORION_CORS_ORIGINS` env 設 production origin

## DB

- 預設 SQLite(env 不設 → 跑 in-memory `:memory:`,重啟全沒)
- Production 用 Postgres:`ORION_DB_URL=postgresql+asyncpg://...`
- 啟動時 `ORION_DB_AUTO_CREATE=true` 自動 create_all(idempotent)

## Multi-tenant

每個 user 一份 messages(by user_id FK)、一份 settings(`/me/settings`)。
User 表內含 hashed password(bcrypt)+ active_session_id。

## Routes 結構

```
src/orion_chat_api/routes/
├── auth.py             /auth/login + /auth/register + /auth/refresh
├── chat.py             /chat/sessions CRUD + /messages
├── models.py           /models 拉 catalog
├── ws_chat.py          /ws/chat WebSocket endpoint
├── oauth.py            /oauth/{provider}/callback
└── me.py               /me/settings + /me/profile
```

## 設計取捨

- **單 process 設計**:FastAPI app 內含 ws + REST + DB pool。Scale-out 走多 instance + sticky session(ws 有 state)。
- **WebSocket per session**:每個對話一條 WS,client 切 session 重新連
- **JWT short-lived + refresh token**:access token 15min,refresh 7 天(rotation on use)

## 限制 / 已知問題

- **WS 沒 reconnect logic on server**:client 斷線 server 看不到 → ghost session 直到 timeout
- **No rate limit**:每 user 沒 RPM cap(orion-model-proxy 有,chat-api 沒)
- **OAuth provider callback localhost**:dev 只能 localhost:8000;prod 要設 public callback

## 未來方向

- **接 orion-model-proxy**:目前 chat-api 直接打 Anthropic / OpenAI;接 proxy 後集中計費
- **Per-org billing**:多 org 場景需要(現只 per-user)
- **Live cursor / collab**:多 user 同 session(co-edit 之類)
- **Push notification(FCM / APNS)**:行動端通知

## 看完繼續

- [web-frontend.md](./web-frontend.md) — React client 怎麼連
- [model-proxy.md](./model-proxy.md) — 集中計費 / 限速
- [`../architecture/packages.md`](../architecture/packages.md) — `orion-chat/api/` 子模組
