# Phase 25:Memory / MCP REST Endpoints(WEB_UI Stage 3 placeholders 接通)

## 速覽

- **預計時程**:3-5 天
- **前置 Phase**:Phase 3(memory)、Phase 5(MCP)、WEB_UI(Stage 3 已建好 placeholder)
- **本文件目的**:WEB_UI Stage 3 的 Memory tab 與 MCP tab 目前是 placeholder
  (顯示「reserved for future phase」),因為 backend 沒對應 REST endpoint。
  本 phase 補上,讓前端 tab 真的能用。

## 為何另開 phase?

WEB_UI Stage 3 完工後,前端三欄佈局齊備、4 個 tab 中:

- Instructions ✓(對應 Phase 13 endpoints)
- Settings ✓(對應 Phase 14 endpoints)
- Memory ❌ placeholder(Phase 3 寫 fs `~/.orion/memory/`,**沒 REST CRUD**)
- MCP ❌ placeholder(Phase 5 `mcp/oauth.py` 是 stub raise NotImplementedError)

兩項都是「需要再開 backend endpoints」的工作,跟 WEB_UI 本身無關;按 user 規範
(completion 不寫 TODO,延後 / nice-to-have 升級為新 phase plan)拆出。

## 任務拆解

### Memory REST 接通

- [ ] 1. `api/routes/memories.py`:
       - `GET /me/memories` → list[Memory](`name / type / description / filename`)
       - `GET /me/memories/{filename}` → 單一全文
       - `PUT /me/memories/{filename}` body 包含 frontmatter + body
       - `DELETE /me/memories/{filename}`
       (per-user,從 `user_memory_paths(user_id)` 操作 fs)
- [ ] 2. 更新 MEMORY.md 的索引(用 Phase 3 既有 `write_index`)
- [ ] 3. 整合 Phase 13 alembic migration(若把 Memory 從 fs 搬 DB 的話 — Phase 25 範圍可選)
- [ ] 4. 前端 `MemorySidebar`(替換 Stage 3 的 placeholder)
       - 顯示 list with type 標籤、name、description
       - 點擊 → modal 展開 body / Edit / Delete
       - 新增按鈕 → 建空 Memory

### MCP OAuth 接通

- [ ] 5. `mcp/oauth.py`:
       - `start_web_oauth_flow(server_name, user_id)` 真實實作(state token + Anthropic OAuth flow)
       - `handle_oauth_callback(state, code)` callback handler
       - Token 存 `storage/secure.py:SecureStorage`(Phase 14 已就緒)
- [ ] 6. `api/routes/oauth.py`:
       - `POST /oauth/start` body `{server: str}` → 回 `{authorize_url, state}`
       - `GET /oauth/callback?state=...&code=...` server-side 處理
       - `GET /oauth/status/{server}` → `{connected: bool}`
- [ ] 7. 前端 `McpConnections`(替換 Stage 3 placeholder)
       - 列固定 server names(github / slack / notion 等)
       - 點 Connect → window.open(authorize_url) + polling status
       - 顯示 ✓ / Connect 狀態

### 收尾

- [ ] 8. 補測試 + 寫 Phase 25 心得

## 依賴

- Phase 3 `memory/`(memory CRUD logic 已存,只需包 REST 殼)
- Phase 5 `mcp/oauth.py`(目前是 stub,要寫 web flow)
- Phase 14 `storage/secure.py`(token 存 keychain / encrypted file)

## 完成後寫

`orion-agent/docs/phase-25-completion.md`(zh-tw、含驗證指令、無 TODO)。
