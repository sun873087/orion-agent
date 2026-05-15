# Web frontend

`apps/orion-chat/web/` — Vite + React + TypeScript 客戶端,連 `orion-chat-api` 跑對話。

**npm name**:`@orion/chat-web`

## 跑

```bash
npm run dev -w @orion/chat-web    # vite :5173,proxy /auth /sessions /chat 等 → :8000
```

或從 root:`make dev-web`。需要 chat-api 同時跑(`make dev-api`)。

## 結構

```
apps/orion-chat/web/src/
├── api/
│   ├── client.ts      apiFetch / apiUpload(REST wrapper)
│   └── auth.ts        token 存取(localStorage)
├── components/
│   ├── ChatView.tsx   主對話畫面
│   ├── MessageList.tsx + MessageBubble.tsx
│   ├── InputBox.tsx
│   ├── Login.tsx
│   ├── Sidebar / SessionList / ModelPicker / ...
│   ├── ConnectionsPanel.tsx (MCP)
│   ├── SettingsPanel.tsx / MemoryPanel.tsx / CustomInstructionsPanel.tsx
│   └── AskUserQuestionDialog.tsx
├── hooks/
│   ├── useSessions.ts
│   ├── useModelCatalog.ts
│   └── ...
├── lib/                ws client、訊息序列化
├── types/
│   ├── api.gen.ts                  ← 自動生成(從 chat-api openapi)
│   ├── ws-client-events.gen.ts     ← 自動生成
│   ├── ws-server-events.gen.ts     ← 自動生成
│   └── events.ts                   ← 手寫(legacy,逐步替換)
└── App.tsx
```

## 型別契約 pipeline

從 chat-api 自動生成 TS types:

```bash
make gen-types
# = npm run gen:openapi + gen:ws-schema + gen:ts-types
```

| Step | 來源 | 產出 |
|---|---|---|
| `gen:openapi` | `chat-api/app.openapi()` | `apps/orion-chat/shared/openapi.json` |
| `gen:ws-schema` | pydantic `ClientEvent` / `ServerEvent` | `shared/ws-{client,server}-events.schema.json` |
| `gen:ts-types` | openapi-typescript + json2ts | `web/src/types/*.gen.ts` |

**寫 web code 時**用生成的 types,不要手寫對應 chat-api 的 schema。chat-api 改了 → 重 generate → TypeScript 編譯期抓到 mismatch。

詳見 [`../guides/update-types.md`](../guides/update-types.md)。

## State 管理

`zustand` store(`store/`)管 session 列表、當前 session、訊息列表。WebSocket events 進來 → reducer 更新 store → React 重 render。

## WebSocket 連線

```typescript
const ws = new WebSocket(`/chat/stream/${sessionId}?token=${jwt}`)
ws.onmessage = (ev) => {
  const event: ServerEvent = JSON.parse(ev.data)
  handle(event)  // 按 type discriminator dispatch
}
```

`vite.config.ts` proxy 把 `/chat/stream/*` 轉到 `ws://localhost:8000`,**proxy `agent: false`** 禁用 connection pool 避免 stale socket(注釋有詳述原因)。

## Auth

- `Login.tsx` POST `/auth/login` → 拿 JWT 存 `localStorage`
- 後續 REST 帶 `Authorization: Bearer <token>` header
- WS 連線網址帶 `?token=<jwt>`(瀏覽器 WebSocket API 不支援 custom header)

## Tailwind + Dark theme

Tailwind utility CSS,主題色透過 CSS variables。有 dark mode toggle。

## 限制 / 未實作

- 沒有 i18n
- 沒有 offline mode
- 大檔上傳沒有分段
- 沒有訊息搜尋
- session 列表沒 pagination(假設使用者 session 不會破百)

## 相關

- [chat-api.md](./chat-api.md) — 後端協定
- [`../guides/update-types.md`](../guides/update-types.md) — 型別契約 pipeline
- [`../guides/manual-testing.md`](../guides/manual-testing.md) — 手動測試流程
