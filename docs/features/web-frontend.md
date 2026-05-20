# Web frontend

`apps/orion-chat/web/` — Vite + React + TypeScript 客戶端,連 `orion-chat-api` 跑對話。

**實作位置**:`apps/orion-chat/web/src/`

## Stack

- Vite + React 18(strict mode)
- TypeScript strict(沒 any 偷渡;`unknown` 進 narrow)
- Zustand state
- Tailwind utility CSS
- WebSocket 跑對話流(reconnect on visibility regain)

## 主要組件

```
web/src/
├── App.tsx                  Routes + auth gate
├── api/                     fetch wrapper + WS client + auth token persist
├── components/
│   ├── Sidebar.tsx          Session list / 切換 / search
│   ├── ChatMain.tsx         Message list + input
│   ├── MessageBubble.tsx    Markdown + tool_use card + thinking
│   ├── Settings.tsx         User profile + connections + models
│   └── ...
└── store/
    ├── auth.ts              JWT + refresh
    ├── chat.ts              messages / busy / error
    └── settings.ts          model / provider / theme
```

## Auth flow

```
1. App load → 看 localStorage token
2. Token 過期 → call /auth/refresh
3. 都失敗 → redirect /login
4. Login → store token + redirect intended page
```

## Streaming

WS receive `{event: "text_delta", data: {text}}` → store.appendDelta → React re-render
component。OS notification 在 background tab 時推。

## 設計取捨

- **Strict TS**:沒 any 偷渡,UI bug 早抓
- **Zustand 不 Redux**:N 個 store(auth / chat / settings),boilerplate 少
- **Tailwind 不 CSS Module**:utility-first,less context switch

## 限制 / 已知問題

- **No offline mode**:沒 service worker,wifi 斷線 = 用不了
- **No virtual scroll**:對話 1000+ messages 會 lag(整 DOM render)
- **OAuth callback 路由限制**:跟 chat-api callback URL 對應的固定路由

## 未來方向

- **Virtual scrolling**:react-window for message list
- **Offline draft**:user 寫一半斷網,reload 自動回來
- **PWA installable**:行動裝置 「加進主畫面」
- **i18n**:目前只 en,加 zh / ja / ...
- **Dark mode 持久化**(已部分有,但跨 setting 一致性差)

## 看完繼續

- [chat-api.md](./chat-api.md) — API server 端
- [cowork.md](./cowork.md) — 桌機 app 對比
