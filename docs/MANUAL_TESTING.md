# Manual Testing Guide(API + UI)

實際把 backend / frontend 跑起來、走過真實對話流程的 step-by-step 指南。
比 unit tests 多一層:**整個系統真的能跑、能對話、檔案上傳能落、樂觀鎖會擋**。

---

## 0. 一次性前置

```bash
# 後端 deps
make -C orion-agent/api install

# 前端 deps(第一次 30-60 秒)
cd orion-agent/frontend && npm install

# Anthropic API key — 真的要對話才需要;只測 UI 框架可跳過
export ANTHROPIC_API_KEY="sk-ant-..."
```

> Anthropic key 沒設,WS 對話送出後會在 backend log 看到 401(模型 API 拒);
> 但 UI 框架本身、CRUD、auth、檔案上傳、settings、cost、permissions
> 都不需要 key,可以照跑。

---

## A. 純 API 測試(curl + ws 工具)

### A1. 起後端(Terminal 1)

```bash
cd orion-agent/api

# DB 模式(custom instructions / user settings / 樂觀鎖才能用)
ORION_DB_URL=sqlite+aiosqlite:///tmp/orion-dev.db \
  uv run orion serve --port 8000
```

→ `Uvicorn running on http://127.0.0.1:8000`。

也可省略 `ORION_DB_URL` 跑 dev 模式 — 那時 `/me/*` endpoints 全 503,但
`/auth/login` 接受任意 username(空密碼),適合純驗 WS。

### A2. 健康 + 註冊 + 登入(Terminal 2)

```bash
# 健康
curl -s http://127.0.0.1:8000/health | jq
# 預期:{"status":"ok"}

# 註冊
curl -s -X POST http://127.0.0.1:8000/auth/register \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"passw0rd"}' | jq

# 登入,把 token 存環境變數方便後續用
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/auth/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"alice","password":"passw0rd"}' | jq -r .token)
echo "TOKEN=$TOKEN"
```

### A3. Sessions CRUD

```bash
# 建 session
SID=$(curl -s -X POST http://127.0.0.1:8000/sessions \
  -H "Authorization: Bearer $TOKEN" | jq -r .session_id)
echo "SID=$SID"

# 列
curl -s http://127.0.0.1:8000/sessions -H "Authorization: Bearer $TOKEN" | jq

# 拿單一
curl -s http://127.0.0.1:8000/sessions/$SID -H "Authorization: Bearer $TOKEN" | jq

# Cost(剛建沒對話 → 0)
curl -s http://127.0.0.1:8000/sessions/$SID/cost -H "Authorization: Bearer $TOKEN" | jq
```

### A4. Custom Instructions(Phase 13)

```bash
# user-level
curl -s -X PUT http://127.0.0.1:8000/me/custom-instructions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"instructions":"Be concise. Use bullet points."}' | jq

curl -s http://127.0.0.1:8000/me/custom-instructions \
  -H "Authorization: Bearer $TOKEN" | jq

# conversation-level
curl -s -X PUT http://127.0.0.1:8000/sessions/$SID/custom-instructions \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"instructions":"This is a code review session."}' | jq
```

### A5. User Settings + 樂觀鎖(Phase 14)

```bash
# 設一筆,version=1
curl -s -X PUT http://127.0.0.1:8000/me/settings/model \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":"claude-opus-4-7"}' | jq

# 樂觀鎖衝突(expected_version 不對 → 409)
curl -s -X PUT http://127.0.0.1:8000/me/settings/model \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"value":"claude-haiku-4-5","expected_version":99}' | jq
# 預期:{"detail":"Version conflict for 'model': expected 99, current 1. Refetch and retry."}

# 列全部 + 刪
curl -s http://127.0.0.1:8000/me/settings -H "Authorization: Bearer $TOKEN" | jq
curl -s -X DELETE http://127.0.0.1:8000/me/settings/model \
  -H "Authorization: Bearer $TOKEN" | jq
```

### A6. 檔案上傳(Phase 11)

```bash
echo "test file content" > /tmp/test.txt

curl -s -X POST http://127.0.0.1:8000/uploads \
  -H "Authorization: Bearer $TOKEN" \
  -F file=@/tmp/test.txt | jq
# 預期:{"upload_id":"...","filename":"test.txt","size":18}

# 列我的 uploads
curl -s http://127.0.0.1:8000/uploads -H "Authorization: Bearer $TOKEN" | jq
```

### A7. WebSocket 對話(需 Anthropic key)

裝 ws 工具(任一):

```bash
npm install -g wscat              # 推薦,訊息易讀
# 或 brew install websocat
```

連線:

```bash
wscat -c "ws://127.0.0.1:8000/chat/stream/$SID?token=$TOKEN"
```

連上後輸入(複製貼上):

```json
{"type":"user_message","content":"What's 2+2?"}
```

預期看到 streaming events:

- `assistant_text`(逐字增量)
- `turn_complete`
- `terminal`

工具呼叫測試:

```json
{"type":"user_message","content":"Read /etc/hosts and tell me the first 3 lines"}
```

預期會收到:

- `tool_use`(模型 call FileReadTool)
- `permission_ask`(server 反問)→ **複製 request_id**
- 回應 permission(decision 四選一):

```json
{"type":"permission_decision","request_id":"<貼複製的>","decision":"allow"}
```

`always_allow` 會把 rule 寫進 `~/.orion/settings.json` 的 `permissions.rules`,
新對話 / 新 session 該 tool 直接過(Phase 13 整合)。

中途取消:

```json
{"type":"abort"}
```

---

## B. UI 測試

### B1. 起後端(同 A1)

### B2. 起前端(Terminal 2)

```bash
cd orion-agent/frontend
npm run dev
```

→ `Local: http://localhost:5173/`,瀏覽器開該網址。

Vite proxy 已設好,前端打 `/auth /sessions /me /uploads /chat` 自動轉
`localhost:8000`,**不用設 CORS**。

### B3. UI 主流程(全跑一次)

| # | 動作 | 預期 |
|---|---|---|
| 1 | Login 頁 → Register tab → username/password(8+ 位) | 註冊成功,自動登入 |
| 2 | 自動進三欄佈局 | 左 Sessions / 中 Chat / 右 4 tab |
| 3 | 左欄點 「+ New」 | 建 session;中欄 header 顯示 session id 前 8 位 |
| 4 | 中欄 header 圓點 | 變綠 = WebSocket 連上 |
| 5 | 輸入框打 `say hi` → ⌘/Ctrl+Enter | user 訊息(藍泡)+ assistant text 逐字進 |
| 6 | turn_complete 後 | 輸入框解鎖,Abort 按鈕消失 |
| 7 | 打 `read /etc/hosts` | ToolUseCard(藍 🔧)→ PermissionDialog(4 按鈕) |
| 8 | 按 「Always allow」 | ToolResultCard(綠 ↳)+ assistant 回應 |
| 9 | 拖一個檔到輸入框 | 看到 📎 chip,顯示檔名 + 大小 |
| 10 | 打文字 + Send | user 訊息含 `[Attached: <name> (upload_id=...)]` |
| 11 | header cost badge | 對話後出現 `$0.0xxx` |
| 12 | 右欄切「Instructions」 | 載入 user-level + per-session;打字 → Save |
| 13 | 右欄切「Settings」 | 列出之前設的 + 新增 model = `"claude-opus-4-7"` |
| 14 | 右欄切「Memory」 / 「MCP」 | 顯示「reserved for future phase」placeholder |
| 15 | 左欄 hover session | 出現 × 按鈕 → 點 → confirm → 刪掉 |
| 16 | 左下 Logout | 回 Login 頁 |
| 17 | 重新 login | sessions 仍在(DB 模式持久) |

### B4. 邊界 / 錯誤情境

| 場景 | 怎麼測 | 預期 |
|---|---|---|
| WS 斷線 | 後端 `Ctrl+C`,前端不重整 | 圓點變灰、輸入框鎖 |
| 後端重啟 | 重啟後端、前端不重整 | 圓點仍灰(沒自動重連 — 已知缺陷) |
| 重整網頁 | F5 / Cmd+R | 重連 ws、session 仍可用 |
| 401 過期 | 改 localStorage `orion.jwt` 成亂碼 → 點任何按鈕 | 自動清 token + 回 Login |
| 大檔案 | 上傳 > 10 MB | 紅色錯誤訊息(backend size limit) |
| 空訊息 | 不打字按 Send | 按鈕 disabled |
| 樂觀鎖衝突 | 開兩個 tab 同 user 同時改同 setting | 後改 → 拿 409 顯示錯誤 |

### B5. 開瀏覽器 DevTools

- **Network → WS**:點 `/chat/stream/...` → 看 frames(send / receive 雙向 JSON)
- **Application → Local Storage**:`orion.jwt` + `orion.username` 兩 key
- **Console**:應該乾淨,沒紅色錯誤

---

## C. 常見坑

| 症狀 | 原因 / 解 |
|---|---|
| 後端起來但 401 connecting WS | `?token=...` 沒帶或過期;重 login |
| `/me/settings` 回 503 | 沒設 `ORION_DB_URL`(dev fallback 模式)|
| `npm run dev` 跑不起來 | 先 `npm install`;Node ≥ 18 必要 |
| 對話沒回應 | 沒 `ANTHROPIC_API_KEY`,或 key 額度耗盡 — 看 backend log |
| 拖檔上傳沒反應 | 拖到 InputBox **內部**(灰底邊框)才行,目前不接受拖到整 ChatView |
| Memory / MCP tab 永遠 placeholder | 設計如此;等 `docs/phases/25-memory-mcp-rest-endpoints.md` 接通 |
| UI 改不生效 | Vite HMR 應該秒更新;真沒就 reload |
| backend mypy/test 跑不起來 | `make -C orion-agent/api install` 重裝(iCloud 偶爾撕掉 .venv pth)|

---

## D. 全自動驗證(配合人工)

人工測試 vs 自動測試的關係:

```
make -C orion-agent/api check      ← 後端單元 / 整合測試(742 case)
       ↓
本檔(MANUAL_TESTING.md)         ← 把後端串前端 / 真模型對話流程
       ↓
production 部署                     ← 換 Postgres / 真 Anthropic key
```

unit tests 顧的是:**單一函式正確**。
本檔顧的是:**整個系統真的接起來能跑、UX 不爆掉**。
production 顧的是:**真實 traffic 不掛**。

---

## E. 用什麼 backend 模式測?

| 模式 | 怎麼起 | 涵蓋 |
|---|---|---|
| **Dev (no DB)** | `uv run orion serve --port 8000` | auth(任意 username 空密碼)、sessions、chat WS、uploads。`/me/*` 全 503 |
| **DB SQLite(本機)** | `ORION_DB_URL=sqlite+aiosqlite:///tmp/orion.db uv run orion serve` | 全部 endpoint,持久;適合手動驗 |
| **DB Postgres(production-ish)** | `ORION_DB_URL=postgresql+asyncpg://... uv run orion serve` | 同上 + Postgres 行為;production 部署前 smoke test |

預設用 SQLite 模式(B 那邊用的),實務上夠涵蓋 90% 場景。

---

## F. 測試完要清?

```bash
# 後端 SQLite DB
rm /tmp/orion-dev.db

# Settings rules(你按過 always_allow / always_deny 寫進這檔)
rm ~/.orion/settings.json    # ← ⚠️ 注意:會清掉所有持久化 settings 與 migration version

# Uploaded files(by user)
rm -rf ~/.orion/uploads/

# Sessions transcripts(per-session JSONL)
rm -rf ~/.orion/sessions/

# 前端 localStorage(在瀏覽器 DevTools → Application 手動清)
```

`~/.orion/` 整個刪掉就回原廠狀態。
