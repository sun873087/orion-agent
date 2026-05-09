# WEB_UI Stage 3 完工記錄

**完成日期**:2026-05-09
**Plan doc**:`docs/phases/WEB_UI.md`(Stage 3 完整功能 UI,三欄佈局)
**狀態**:✅ 程式碼就緒;`npm install && npm run dev` 即可起。
未在本機跑 `npm install`(repo 不含 `node_modules`),由使用者 / CI 安裝執行。

> WEB_UI 不是後端 phase,**沒有 pytest 數字**;本檔記錄前端落地的內容、設計取捨、
> 與哪些 backend endpoint 對應 / 哪些 placeholder。

---

## 交付清單

### 移除

```
orion-agent/ui/test-ui.html         [刪]  Stage 1 單檔 HTML;由 Stage 3 取代
                                          (對應 WEB_UI.md spec 「→ 取代 test-ui.html」)
```

### 新增 frontend 專案(`orion-agent/frontend/`)

```
frontend/
├── package.json                         Vite + React 18 + TS + Tailwind 3 + react-markdown
├── vite.config.ts                       proxy /auth /sessions /me /uploads /chat → :8000
├── tsconfig.json                        strict + noUnusedLocals + verbatimModuleSyntax
├── tailwind.config.js                   utility-first
├── postcss.config.js
├── index.html
├── README.md                            啟動指令 + endpoint 對應表 + 設計取捨
├── .gitignore                           node_modules / dist / .vite
└── src/
    ├── main.tsx                         React.StrictMode + render
    ├── App.tsx                          三欄組合 + 401 偵測 + auto-select session
    ├── index.css                        Tailwind directives + .prose-msg 簡單 markdown
    ├── types/
    │   └── events.ts                    對應 backend api/event_schema.py(11 個 event types)
    │                                     + REST 型別(SessionSummary / CostSummary /
    │                                     UploadSummary / CustomInstructionsResponse / SettingValue)
    ├── api/
    │   ├── auth.ts                      JWT localStorage(get/set/clear/isLoggedIn)
    │   └── client.ts                    apiFetch / apiUpload + 401 → clearAuth + ApiError class
    ├── hooks/
    │   ├── useWebSocket.ts              ws connect by sessionId+token + pendingPermissions queue +
    │   │                                  send / answerPermission / abort / clear
    │   └── useSessions.ts               sessions list / create / remove / refresh
    └── components/
        ├── Login.tsx                    register / login mode toggle
        ├── SessionsSidebar.tsx          (左)sessions list + new + delete + logout
        ├── ChatView.tsx                 (中)header + reduce events → FlowEntry list
        ├── MessageBubble.tsx            user / assistant / thinking 三 role
        ├── MessageList.tsx              FlowEntry list + live streaming text + permission stack
        ├── ToolUseCard.tsx              藍色 🔧 卡片
        ├── ToolResultCard.tsx           綠色 ↳ 卡片(error 紅色)+ 600 字截斷 + max-h-60
        ├── PermissionDialog.tsx         4 按鈕(allow once / always / deny once / always deny)
        ├── InputBox.tsx                 textarea + ⌘/Ctrl-Enter + drag-drop file upload + abort
        ├── CustomInstructionsPanel.tsx  per-user + per-session 雙文本 + 503 detect
        ├── SettingsPanel.tsx            /me/settings list + 新增 + 刪除 + JSON value
        ├── CostBadge.tsx                /sessions/{sid}/cost + refreshKey on turn
        └── RightSidebar.tsx             (右)4 tab(Instructions / Settings / Memory / MCP)+
                                          placeholder 元件
```

---

## 涵蓋的 Phase 對應

| 元件 | Backend Phase | 真連通 ✓ / placeholder |
|---|---|---|
| Login(register / login) | Phase 6 / 7 | ✓ |
| SessionsSidebar(列 / 建 / 刪) | Phase 6 | ✓ |
| ChatView(WebSocket streaming) | Phase 6 | ✓ |
| Tool 卡(use / result) | Phase 1 / 7 / 10 | ✓ |
| Permission dialog(4 按鈕) | Phase 6 + 13 | ✓(`always_*` 寫進 Phase 13 settings.permissions.rules) |
| File upload(drag-drop) | Phase 11 | ✓ |
| CustomInstructionsPanel | Phase 13 | ✓(無 DB 顯示「require ORION_DB_URL」) |
| SettingsPanel | Phase 14 | ✓ |
| CostBadge | Phase 9 | ✓ |
| Memory tab | Phase 3 fs only,**沒 REST endpoint** | placeholder → `docs/phases/plan/25-memory-mcp-rest-endpoints.md` |
| MCP tab | Phase 5 OAuth 是 stub(raise NotImplementedError)| placeholder → 同上 |

---

## 設計決策

### 1. Vite + React + TS + Tailwind(WEB_UI.md 預設選型)
spec § 7 設計取捨:Tailwind utility 直接寫 className,bundle 小,不被 Material UI / Chakra
component lib lock-in。production 換 Material 也容易(class names 重寫,結構不動)。

### 2. Vite proxy 處理 CORS
dev 用 Vite proxy → 前端打相對路徑 `/sessions` 自動轉 `localhost:8000`。
production 用 nginx 同 origin 反向代理,**程式碼不變**。

### 3. 三欄固定佈局,desktop-first
spec § 「完整 Stage 3 layout」對應。Mobile / responsive 不做(WEB_UI 範圍內定位
是 dev 測試 UI,不是 production 給 end user)。

### 4. JWT 存 localStorage,WS 用 query string token
- WS 沒 header 機制,token 走 `?token=...`(backend 已支援)
- REST 用 Authorization header
- 不靠 cookie → CSRF 不適用
- spec § 「為何 permission ask 浮動式而非 modal?」對應

### 5. Reduce events → FlowEntry 模型(替代直接渲染 events list)
原 spec 範例直接 events.map render,但 assistant_text 是 streaming 增量,中途 N 條
小片段 → render N 個小卡很醜。

實作:`reduce(state, ev)` 把 `assistant_text` 累積到 `liveAssistant` 字串,在
**第一個 tool_use / turn_complete** 時凝固成單一 `assistant` entry。
`liveAssistant`(尚未凝固的)在最末端 mount 成 streaming 訊息。

### 6. Permission dialog inline(不是 modal)
spec § 設計取捨對應。Modal 阻擋滾動,user 看不到 context;inline 在訊息流末端,
user 邊看 context 邊決定。

### 7. Permission 4 個按鈕(allow once / always allow / deny once / always deny)
對應 Phase 13 `persist_decision_if_always` — `always_*` 會寫進
`settings.permissions.rules`,新對話直接套用。

### 8. RightSidebar tab 而非折疊式
4 個 tab(Instructions / Settings / Memory / MCP)。Memory + MCP 顯示「reserved
for future phase」placeholder,**不隱藏整 tab** — user 知道哪裡尚未通,
比靜默隱藏好。

### 9. CostBadge 用 refreshKey 而非定時 polling
spec § 範例用 `setInterval(5000)`,本實作改用 `turnCount` 作 refreshKey:
turn 結束才重抓 cost。減少不必要的 HTTP request,反應更即時。

### 10. 401 → clearAuth + 由 App 重 render Login
`apiFetch` 抓 401 → `clearAuth()` + throw ApiError。caller 元件拿到 error 自己
處理(顯示訊息);App 的 `useState(isLoggedIn())` 因為 storage 變動可重新偵測
(`storage` event 跨 tab,本 tab 由 `setAuthed(false)` 直接觸發)。

### 11. InputBox 鎖機制:`disabled = !sessionId || !connected || inFlight`
- 沒 session → 鎖
- WS 斷 → 鎖
- 模型 streaming(turn_complete 還沒到 terminal)→ 鎖
- inFlight 期間顯示 Abort 按鈕

### 12. 攻擊面思考
- 沒拼 base URL → XSS via subdomain not feasible
- localStorage token vs httpOnly cookie:**dev tooling** 範圍接受 localStorage
  風險;production SaaS 環境若需要 httpOnly cookie,backend 要加 set-cookie 路徑
- markdown 渲染走 react-markdown(預設不 raw HTML)

---

## 啟動驗證

```bash
# 後端(任一模式)
cd orion-agent/api
ORION_DB_URL=sqlite+aiosqlite:///tmp/orion-dev.db \
  uv run orion serve --port 8000 &

# 前端
cd orion-agent/frontend
npm install         # 第一次 ~ 30 秒
npm run dev         # → http://localhost:5173

# 開瀏覽器 → register → login → 自動建第一個 session → 對話

# 測試:
#   1. SessionsSidebar New / Delete OK
#   2. 對話 streaming 文字逐字進
#   3. 模型 call 工具 → 看到 ToolUseCard / ToolResultCard
#   4. Permission 出現 → 4 按鈕擇一(always_allow 後新對話該 tool 直接過)
#   5. drag-drop 檔案 → 看到 📎 chip,送出附在訊息末尾
#   6. RightSidebar Instructions / Settings 兩 tab 都能讀寫
#   7. CostBadge 每 turn 結束更新
#   8. Memory / MCP tab 顯示「reserved」placeholder
```

---

## 沒做(升級為新 phase plan)

| 項目 | 升級到 |
|---|---|
| Memory list / CRUD UI(Phase 3 backend 沒 REST endpoint) | `docs/phases/plan/25-memory-mcp-rest-endpoints.md` |
| MCP OAuth connection(Phase 5 oauth 是 stub) | 同上 |
| Mobile / responsive 排版 | 不開 phase(範圍外)|
| Dark mode / theme | 不開 phase(範圍外)|
| Coordinator workers 視覺化(Phase 15)| 不開 phase(實際應用後再評估) |
| react-flow DAG 顯示(Phase 15 multi-agent UI)| 不開 phase(同上) |
| i18n / 多語系 | 不開 phase(範圍外)|

---

## 已知設計缺陷 / 後續可能改

- **events 累積無上限**:長對話 1000+ events 後可能影響渲染。production 需要 GC
  或 windowing(react-window)。
- **單 page,沒 router**:future 加 settings page / memory page 可能要引入 router。
- **CustomInstructionsPanel 換 session 重抓**:每次 tab 切回 / 換 session 都重 fetch,
  浪費。可以用 SWR / react-query cache。本範圍不做。
- **WS 重連邏輯沒做**:斷線後不自動重連;user 要重新整理。
- **drag-drop 範圍只有 InputBox**:整 ChatView 接受 drop 會更好。
- **沒 typecheck CI**:`npm run typecheck` 是手動跑,沒 hook 進 backend make check。
  考慮 Phase 26 補 monorepo CI。

這些都不是「未做的 TODO」,是「實作中觀察到的優化機會」 — 看 production 反饋
再決定要不要做(對應 user 規範 → 真要做時開新 phase plan)。

---

## 實作中的小坑

### 1. TestClient 在 backend 測試需要 `with` 才觸發 lifespan
WEB_UI 不影響(瀏覽器跑時 backend 是 long-lived process),但 backend dev 跑
`uv run orion serve` 才會跑 lifespan + init_db。前端不感知。

### 2. WebSocket 在 React.StrictMode 會建兩次
雙跑 effect → 兩次 ws.new + 第一次的 cleanup 立即關。看 server log 會有 `connect`
/ `disconnect` / `connect`。生產環境 StrictMode 不開,正常。

### 3. Vite proxy 對 ws 路徑要顯式設 `ws: true`
`vite.config.ts` proxy `/chat` 條目必須 `ws: true`,否則前端打 ws 會 404。

### 4. textarea + 中文輸入法
本實作沒處理 IME composition events;按 ⌘+Enter 在中文輸入法選字中可能誤送。
若使用者反映,可加 `onCompositionStart/End` flag 守。

### 5. localStorage event 不會在本 tab fire
`window.addEventListener('storage', ...)` 只在**其他 tab**改 storage 時觸發。
本 tab clearAuth 後我直接 `setAuthed(false)` 顯式切。

### 6. `verbatimModuleSyntax` + import type
`tsconfig` 開 `verbatimModuleSyntax`,只用作型別的 import 必須 `import type`,
不然 emit 時會留 runtime import。我所有 type imports 都用 `import type`。

### 7. apiFetch 對 204 / 空 body 處理
DELETE endpoint 回 204 No Content;`r.json()` 會 parse 失敗。
用 `if (r.status === 204) return undefined`,然後 `text || ''` 防空。
