# Phase 25 完工記錄 — Memory + MCP OAuth REST endpoints

**完成日期**:2026-05-10
**Plan doc**:`docs/phases/25-memory-mcp-rest-endpoints.md`(原 `docs/phases/plan/25-...`,完工後搬出)
**狀態**:✅ Memory + MCP OAuth web flow 完整接通,Settings → Memory / Connections
分頁不再是 placeholder。
**測試**:`tests/unit/api/test_memories_routes.py`(9 tests)+
`tests/unit/api/test_oauth_routes.py`(10 tests),全 pass。

---

## 交付清單

### 後端新增

```
api/src/orion_agent/
├── api/routes/
│   ├── memories.py                     # /me/memories CRUD(per-user fs)
│   └── oauth.py                        # /oauth/* web flow
└── mcp/oauth.py                        # 重寫(原本是 stub raise NotImplemented)

api/tests/unit/api/
├── test_memories_routes.py             # 9 tests
└── test_oauth_routes.py                # 10 tests(含 dev-mock end-to-end)
```

### 後端修改

```
api/src/orion_agent/api/app.py          # 註冊 memories + oauth router
```

### 前端新增

```
frontend/src/components/
├── MemoryPanel.tsx                     # list / view / edit / create / delete
└── ConnectionsPanel.tsx                # provider list + Connect/Disconnect
```

### 前端修改

```
frontend/src/components/SettingsModal.tsx   # 拿掉 Placeholder,接上 MemoryPanel + ConnectionsPanel
frontend/vite.config.ts                     # proxy /oauth → :8000
```

---

## Memory REST 設計

直接包既有 `memory.scan` / `memory.paths` 模組,**不搬 DB**(Phase 3 設計就是 fs)。

| Method | Path | 行為 |
| --- | --- | --- |
| GET | `/me/memories` | list(filename / name / description / type),不含 body |
| GET | `/me/memories/{filename}` | 單一含 body |
| PUT | `/me/memories/{filename}` | 新建或覆蓋,寫完 rescan + 重寫 MEMORY.md 索引 |
| DELETE | `/me/memories/{filename}` | idempotent;刪後 rescan 索引 |

寫入 body schema:

```json
{
  "name": "短標題",
  "description": "一句話摘要(relevance ranker 看這個)",
  "type": "user|feedback|project|reference|null",
  "body": "memory 主體 markdown"
}
```

寫入時後端把 4 個欄位重組成 `---\nname: ...\ndescription: ...\ntype: ...\n---\n<body>`,
再 round-trip 給 `parse_frontmatter` 驗證 — 若 name / description 含換行造成解析失敗
就 422,提示使用者去掉換行。

### Filename 安全

`^[A-Za-z0-9._-]+\.md$` regex:擋路徑分隔、`..`、空白、特殊字元。`MEMORY.md` 額外
擋(它是索引,不該透過 REST 編)。違規 → 422。

per-user 隔離靠 `user_memory_paths(user_id)` 直接接 `current_user` JWT
dependency,fs 路徑寫到 `~/.orion/users/<uid>/memory/` 自動分桶。alice 寫的
不會出現在 bob 的 list 裡(`test_per_user_isolation` 證明)。

---

## MCP OAuth Web Flow 設計

Phase 5 留的 `mcp/oauth.py` stub 拆成三層:

### 1. Provider registry

```python
@dataclass(frozen=True)
class OAuthProvider:
    name: str           # storage key + URL segment
    label: str          # UI 顯示
    authorize_url: str
    token_url: str
    scopes: list[str]
    client_id_env: str | None
    client_secret_env: str | None
```

內建三個:

- `dev-mock` — 不打外部,callback 自行短路寫 fake token。**讓 e2e 測可以離線跑**
- `github` — `GITHUB_OAUTH_CLIENT_ID` / `_SECRET`(沒設 env → `available=False`,
  UI disable Connect 按鈕)
- `linear` — 同上,`LINEAR_OAUTH_CLIENT_ID` / `_SECRET`

加新 provider 直接 append `_BUILTIN_PROVIDERS`(下一個 phase 可改成讀
`mcp.json` 的 oauth 區段)。

### 2. State store(in-memory + 5 min TTL)

```python
_state_store: dict[str, _StateRecord]
_state_lock = asyncio.Lock()
```

`secrets.token_urlsafe(24)` 產 random state,record 含 `(server_name, user_id,
redirect_uri, created_at)`。**one-shot** — `_take_state` 取一次後 pop;重 callback
同 state 會 400(`test_state_one_shot` 驗證)。

> 多 worker / 重啟會掉 state — OAuth flow 本來就 < 1 min,故意不持久化簡化。
> 真要跨 worker 改 Redis 是後續 phase。

### 3. Token storage

走 Phase 14 的 `SecureStorage`(keychain 為主,fallback `~/.orion/secrets.enc`
Fernet 加密檔)。Key 格式 `mcp:<server>:<user_id>`,值是 JSON:

```json
{
  "access_token": "...",
  "refresh_token": "..." | null,
  "expires_at": 3600 | null,
  "raw": { /* 原始 token endpoint response */ }
}
```

refresh token 邏輯 deferred — Phase 25 範圍只到 obtain + persist。

### 4. REST endpoints

| Method | Path | 行為 |
| --- | --- | --- |
| GET | `/oauth/providers` | list(name / label / available) |
| POST | `/oauth/start` body `{server}` | 回 `{authorize_url, state}` |
| GET | `/oauth/callback?state=...&code=...` | 第三方 redirect 進來,寫 token,render close-window HTML |
| GET | `/oauth/status/{server}` | `{server, label, available, connected}` |
| DELETE | `/oauth/{server}` | 刪 token |

**callback 不要求 Bearer token**:第三方 redirect 過來瀏覽器不會帶 Authorization
header。state 充當 user 證明 — 它是 server 自己頒發的 short-lived random token
+ 綁 user_id。

### 5. 前端 flow

```
ConnectionsPanel
  ├─ GET /oauth/providers + GET /oauth/status/<each> 並行
  └─ Connect 按鈕
       ├─ POST /oauth/start { server }
       ├─ window.open(authorize_url, 'orion-oauth', popup-spec)
       └─ setInterval polling /oauth/status/<server> 每 1.5s
            ├─ connected=true → stopPolling + refresh + popup.close()
            ├─ popup.closed → 'OAuth window closed before completion'
            └─ > 5min → timeout
```

dev-mock 因為 authorize_url 直接打回 callback,popup 開了之後 < 1s 就完成,UI
看起來就是「按下 Connect → 出現 ✓ Connected」。

---

## 動到的檔案清單

```
新增:
  api/src/orion_agent/api/routes/memories.py
  api/src/orion_agent/api/routes/oauth.py
  api/tests/unit/api/test_memories_routes.py
  api/tests/unit/api/test_oauth_routes.py
  frontend/src/components/MemoryPanel.tsx
  frontend/src/components/ConnectionsPanel.tsx

修改:
  api/src/orion_agent/api/app.py             # 註冊 2 個 router
  api/src/orion_agent/mcp/oauth.py           # 從 stub 改成完整 web flow
  frontend/src/components/SettingsModal.tsx  # 拿掉 Placeholder
  frontend/vite.config.ts                    # proxy /oauth → :8000
```

無動到 SecureStorage、memory.scan、memory.paths(設計層級不變,只新增 REST 殼)。

---

## 驗證

### 跑後端測試

```bash
cd orion-agent/api
uv sync                   # 確保 editable install 在 venv 內(若被 uv reinstall 弄亂)
uv run pytest tests/unit/api/test_memories_routes.py tests/unit/api/test_oauth_routes.py -v
```

預期:`19 passed`。

> uv 在某些 inplace 安裝(如 mcp 1.27.1 missing RECORD)後重跑 pytest 會在
> reinstall 的同時把 orion_agent editable install 弄掉,出現
> `ModuleNotFoundError: No module named 'orion_agent'`。Workaround:
> 重新 `uv sync` 一次。已知 `uv` issue,跟本 phase 無關。

### 手動跑全棧

1. `cd orion-agent/api && ORION_DB_URL=sqlite+aiosqlite:///./dev.db uv run uvicorn orion_agent.api.app:app --reload`
2. `cd orion-agent/frontend && npm run dev` → http://localhost:5173
3. 註冊 / 登入
4. **Memory tab 驗證**:
   - 右上齒輪 → Settings → Memory
   - 列表初始空。按 **New** → 填 `name="Likes Python"`、
     `description="senior Python engineer"`、type=`user`、body=`Anything`
   - Save → 列表出現一條,filename 自動產生 `likes_python.md`
   - 點開 → modal 顯示完整內容、可改、可存
   - hover delete icon → 確認後消失,fs `~/.orion/users/<uid>/memory/` 對應檔被刪
5. **Connections tab 驗證(dev-mock)**:
   - Settings → Connections
   - 看到 `Dev Mock` / `GitHub`(Not configured)/ `Linear`(Not configured)
   - 點 `Dev Mock` 旁的 **Connect**
   - 短暫看到 popup 自動完成(它直接 redirect 到 callback)
   - 列表更新成 `✓ Connected`
   - **Disconnect** → 確認 → 變回 Not connected
6. **Connections tab 驗證(real GitHub,選做)**:
   - GitHub Settings → Developer settings → OAuth Apps → New
   - Authorization callback URL 填 `http://localhost:8000/oauth/callback`
   - 拿到 client_id / client_secret,啟 backend 前 `export
     GITHUB_OAUTH_CLIENT_ID=...; export GITHUB_OAUTH_CLIENT_SECRET=...`
   - 重啟 backend,Connections tab 的 GitHub 應該變成可 Connect
   - 按 Connect → popup 跳到 GitHub authorize → 同意 → 自動 close → 列表 ✓

### 直 hit API

```bash
TOKEN=$(curl -s -X POST http://localhost:8000/auth/login \
  -H 'content-type: application/json' \
  -d '{"username":"alice","password":"passw0rd"}' | jq -r .token)

# Memory CRUD
curl -s -X PUT http://localhost:8000/me/memories/test.md \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"name":"t","description":"d","type":"user","body":"hello"}'

curl -s http://localhost:8000/me/memories \
  -H "Authorization: Bearer $TOKEN"

# OAuth dev-mock
curl -s -X POST http://localhost:8000/oauth/start \
  -H "Authorization: Bearer $TOKEN" -H 'content-type: application/json' \
  -d '{"server":"dev-mock"}'
# → {"authorize_url":"http://localhost:8000/oauth/callback?state=...&code=dev-mock-code", "state":"..."}
# 直接 GET 那個 url 後再
curl -s http://localhost:8000/oauth/status/dev-mock \
  -H "Authorization: Bearer $TOKEN"
# → {"connected": true, ...}
```

---

## 設計取捨

### Memory 為什麼不搬 DB

Phase 3 既有 fs layout(`~/.orion/users/<uid>/memory/*.md`)是 markdown — user
可以 git 管、可以用編輯器改、scan 工具可以直接讀。搬 DB 失去這些好處,且本
phase 的 client 只有 web UI 一個,fs 完全夠用。Phase 25 plan 步驟 3 標
「Phase 25 範圍可選」也是這個道理 — 跳過。

### OAuth state store 為什麼不持久化

OAuth state token 的本質是 short-lived nonce(< 1 min flow),pickle 進 DB 是
overengineering。in-memory + lock 簡單、零依賴,multi-worker 一致性等 Redis
入場時(production deploy)再處理是更合理的時機。

### dev-mock 為什麼是 first-class provider 而不是 test fixture

放 fixture 內只能 unit test 用,**手動驗證和 e2e 都要重 stub**。內建成 provider 後:

- unit test 直接打 dev-mock 走完整 flow,不 stub httpx
- 手動跑(無 GitHub OAuth app)也能驗 UI 流程
- 開發者 debug 前端 polling 邏輯不需要真連外網

代價:正式部署時 dev-mock 仍會出現在 list。**這不是安全問題** — token 是
`dev-mock-token-<uid>`,沒實際權限,不能拿來打任何 API。但若覺得礙眼,後續
phase 可加 `ORION_DISABLE_DEV_OAUTH_PROVIDERS=1` env gate。

### Token refresh 為什麼 deferred

GitHub token 不過期,Linear refresh token 規則複雜(不同 scope 不同 TTL),做
完整 refresh 邏輯需要 per-provider 客製。Phase 25 範圍是「能取得並安全儲存」,
refresh 等 user 真實踩到 expired 再開 phase。

### `OAuthProvider` 為什麼是 dataclass 不是 ABC

Provider 之間差別只在 URL / scopes / env var 名稱,**沒有 polymorphic 行為**。
ABC + subclass 是 Java thinking;dataclass 一筆描述就完了,加新 provider
append 一行就行。

---

## 已知 caveat

### 1. callback URL 寫死從 `request.base_url`

`_redirect_uri(request) = f"{request.base_url}/oauth/callback"`。本機 dev 拿到
`http://localhost:8000/oauth/callback`,production 走 reverse proxy 必須讓
proxy 帶對 `Host` / `X-Forwarded-Proto` header,否則 Starlette 算出來的
`base_url` 會錯(可能是 `http://app:8000` internal name)。
Workaround:用 `uvicorn --proxy-headers --forwarded-allow-ips='*'` 啟動。

### 2. popup blocker 友善度

`window.open` 必須在 user click handler 同步呼叫才不被 popup blocker 擋。
ConnectionsPanel 的 `connect()` 是 async — 第一次點按鈕會先 await POST `/oauth/start`,
**回來後**才呼叫 `window.open`。在 Safari 嚴格模式下會被 block。
若使用者反映,把 popup 改先開白頁、API 回來再 `popup.location = authorize_url`。

### 3. dev-mock 之外的 provider scopes 寫死

GitHub 寫死 `["repo", "read:user"]`,Linear `["read", "write"]`。要客製 scope
得改 source code,沒做 env override。下個 phase(若需要)可以加
`GITHUB_OAUTH_SCOPES=repo,read:user` env。

### 4. `_storage` module global

OAuth backend 是 module-level singleton,跑多個 FastAPI app instance(罕見)
會共用。`reset_backend_for_tests` 是 escape hatch 給單測 inject。production 不會踩到。

### 5. uv 環境穩定性

跑單測時 `uv run pytest` 偶發
`ModuleNotFoundError: No module named 'orion_agent'`,因為 uv 偵測到 venv 內
某些套件 `RECORD` 缺檔會 reinstall,過程中 editable install 被踢出來。
**workaround**:再 `uv sync` 一次重灌 editable install。跟本 phase 無關。
