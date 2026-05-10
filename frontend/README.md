# Orion Agent — Frontend(WEB_UI Stage 3)

對應 `docs/phases/WEB_UI.md` § 「完整功能 UI(Phase 11+)」三欄佈局。

```
┌────────────┬────────────────────────────┬──────────────────┐
│ Sessions   │  ChatView                  │  Right tabs      │
│ sidebar    │  (header + msg list +      │  Instructions /  │
│ (login /   │   tool cards + perm prompt │  Settings /      │
│  logout)   │   + input + file upload)   │  Memory / MCP)   │
└────────────┴────────────────────────────┴──────────────────┘
```

## 啟動

```bash
# 1. 後端先跑(任一,擇一)
cd ../api
ORION_DB_URL=sqlite+aiosqlite:///tmp/orion-dev.db \
  uv run orion serve --port 8000
#   ↑ DB 模式(custom instructions / user settings 才能用)
# 或
uv run orion serve --port 8000
#   ↑ Dev 模式(任意 username + 空密碼 login;DB-only endpoint 會 503)

# 2. 前端 dev server
cd ../frontend
npm install
npm run dev      # → http://localhost:5173

# 3. 瀏覽器開 http://localhost:5173
```

Vite proxy 已設定把 `/auth /sessions /me /uploads /chat` 轉 `localhost:8000`,
不用改 CORS。

## 用什麼

- **Vite + React 18 + TypeScript**(strict)
- **Tailwind CSS 3**(utility-first,bundle 小)
- **react-markdown + remark-gfm**(訊息流的 markdown 渲染)
- **Zustand**(列在 deps,本版尚未實際使用 — 留給未來複雜全域 state)

不用 React Router(只有一頁);不用 Redux(state 簡單)。

## 對應後端 endpoint

| Frontend 元件             | Endpoint                                                                         | Phase                                    |
| ------------------------- | -------------------------------------------------------------------------------- | ---------------------------------------- |
| `Login`                   | `POST /auth/register`、`POST /auth/login`                                        | 6 / 7                                    |
| `SessionsSidebar`         | `GET/POST/DELETE /sessions`                                                      | 6                                        |
| `ChatView`                | `WS /chat/stream/{sid}?token=...`                                                | 6                                        |
| `InputBox`(file upload)   | `POST /uploads`                                                                  | 11                                       |
| `CustomInstructionsPanel` | `GET/PUT /me/custom-instructions`、`GET/PUT /sessions/{sid}/custom-instructions` | 13                                       |
| `SettingsPanel`           | `GET/PUT/DELETE /me/settings`                                                    | 14                                       |
| `CostBadge`               | `GET /sessions/{sid}/cost`                                                       | 9                                        |
| `Memory` tab              | (placeholder)                                                                    | Phase 3 沒 REST endpoint;留新 phase plan |
| `MCP` tab                 | (placeholder)                                                                    | Phase 5 OAuth 是 stub;留新 phase plan    |

## 設計取捨

### Vite proxy 而非絕對 URL

dev 用 proxy → 前端 fetch `/sessions` 等相對路徑,proxy 轉 `localhost:8000`。
production 部署用 nginx reverse proxy 或同 origin,程式碼不變。

### JWT 存 localStorage

簡單。CSRF 不適用(WS 用 query string token + REST 用 Authorization header,不靠 cookie)。
Token 過期由 `apiFetch` 抓 401 自動 `clearAuth` + 觸發重 login。

### Tab-based 右側欄

Memory / MCP 等後端 endpoint 還沒做的功能,顯示 placeholder + 「reserved for future
phase」訊息。比隱藏整 tab 更清楚 — user 知道哪邊還沒接通。

### Permission dialog 浮動式(不是 modal)

inline 顯示在訊息流末端,user 可以滾上去看 context。對應 spec WEB_UI.md 設計取捨。

### 沒做(未來 phase 接)

- Memory list 讀寫 UI(需 backend 加 REST endpoint)
- MCP OAuth connection flow(Phase 5 OAuth 是 stub)
- 多語系 / i18n
- Theme(dark mode)
- Mobile 版排版(目前是 desktop fixed three-column)

## 開發小提示

- TypeScript `strict` + `noUnusedLocals` 全開
- 換 backend WS schema → 同步改 `src/types/events.ts`
- 加新 backend endpoint → 同時加 `src/api/client.ts` wrapper(若需要)+ 元件
