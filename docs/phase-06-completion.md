# Phase 6 — FastAPI Layer 完工記錄

**完成日期**:2026-05-07
**Spec doc**:`docs/phases/06-fastapi-layer.md`
**狀態**:✅ make check 全綠(311 tests),uvicorn live demo REST 流程跑通

---

## 交付清單

```
src/orion_agent/api/                     [全新,11 檔]
├── __init__.py
├── app.py                       FastAPI app + lifespan + CORS + 路由註冊
├── event_schema.py              ws event Pydantic discriminated union(client + server)
├── session_manager.py           in-memory dict[(user_id, session_id), Conversation]
├── auth.py                      JWT issue/verify(dev mode + ORION_JWT_SECRET env)
├── deps.py                      get_session_manager / get_llm_provider / current_user
│                                (用 HTTPConnection 同時支援 HTTP + WebSocket)
├── ws_permissions.py            make_can_use_tool_for_websocket(read-only auto-allow,
│                                其他推 PermissionAskEvent + 60s timeout)
└── routes/
    ├── __init__.py
    ├── health.py                /healthz
    ├── auth.py                  /auth/login
    ├── sessions.py              /sessions(POST/GET/DELETE)— user 隔離
    └── chat.py                  /chat/stream/{session_id}(WebSocket;writer/reader/runner 三 task)

修改既有檔(3 檔):
├── main.py                      新增 `serve` subcommand(typer)
├── pyproject.toml               fastapi / uvicorn[standard] / pyjwt deps
└── ui/test-ui.html              全面對齊本 phase event schema + JWT 登入流程
```

### Tests(全新,8 檔,37 案例)

```
tests/unit/api/
├── test_event_schema.py         8 tests(parse / serialize / 邊角)
├── test_session_manager.py      6 tests(create/get/delete/list/user 隔離)
├── test_auth.py                 6 tests(token round-trip / login endpoint / bearer)
├── test_health.py               1 test
├── test_sessions.py             7 tests(REST CRUD / user isolation / 404)
├── test_ws_permissions.py       5 tests(read-only auto-allow / ask-deny / timeout)
└── test_chat_ws.py              4 tests(WebSocket 完整 round-trip + 錯誤 case)
```

---

## 驗證結果

### Static + tests

| 檢查 | 結果 |
|---|---|
| `ruff check` | ✅ |
| `mypy --strict` | ✅(84 → 96 source files) |
| `pytest tests/unit/` | ✅ **311 passed**(274 → 311,+37) |

### Live uvicorn demo

```bash
$ uv run orion serve --port 8765 &

# /healthz
$ curl http://127.0.0.1:8765/healthz
{"status":"ok"}

# /auth/login
$ curl -X POST http://127.0.0.1:8765/auth/login \
    -H 'Content-Type: application/json' -d '{"username":"alice"}'
{"token":"eyJ...", "user_id":"alice", "expires_at":"2026-05-08T..."}

# /sessions create + list
$ curl -X POST .../sessions -H "Authorization: Bearer $TOKEN"
{"session_id":"09483fd1-...","user_id":"alice","n_messages":0,"n_turns":0}

$ curl .../sessions -H "Authorization: Bearer $TOKEN"
[{"session_id":"09483fd1-...","user_id":"alice","n_messages":0,"n_turns":0}]
```

### test-ui.html 流程

`ui/test-ui.html` 已全面對齊本 phase API:
1. Login button → POST /auth/login → 存 JWT
2. New Session button → POST /sessions → 取 session_id → connectWS 自動帶 ?token=...
3. ws.send_json + handleEvent 對應 ServerEvent union
4. PermissionAskEvent 動態產 Allow/Always/Deny 三按鈕,answer 走 ws

開瀏覽器測試:`open ui/test-ui.html`(注意 CORS:`null` origin 已 whitelist)。

---

## 與 spec doc 的差異

| 項目 | spec | 實作 | 為何 |
|---|---|---|---|
| 模組命名 | `claude_agent_py.api` | `orion_agent.api` | 沿用 Phase 0 |
| `Conversation.submit_message` | spec 假設 method | 我們是 `Conversation.send` async generator | Phase 1 既有設計 |
| `_message_to_event(SDKMessage)` | spec 用 SDKMessage | 我們用 `_loop_to_server_events(LoopEvent)` | Phase 1 LoopEvent 對應 |
| Resume API | spec 暗示 Phase 7 才做 | 不做 — POST /sessions 只建新 | 與 spec 一致 |
| MCP web OAuth | 完全未明寫 | 不做 | Phase 7 / 11+ |
| Conversation 接 McpManager | spec 未明寫 | 暫不 — chat.py per-session 不啟 manager | manager lifecycle 太重,Phase 7 整合 |

---

## 實作中發現的細節 / 坑

### 1. FastAPI Depends 不吃 `Request | None` 簽名

我嘗試 `def get_session_manager(request: Request | None = None, websocket: WebSocket | None = None)`
讓同函式吃 HTTP / WS,但 FastAPI 把 `Request | None` 當成 Pydantic 欄位(因為 `| None`),
直接 raise FastAPIError。

**正解**:用 `starlette.requests.HTTPConnection` — Request 與 WebSocket 的 base class,
FastAPI 兩種 route 都自動注入。

### 2. anyio.MemoryObjectSendStream 不是 asyncio.Queue

`MemoryObjectSendStream` 用 `.send()`,`asyncio.Queue` 用 `.put()` / `.get()`。我搞混。
ws_permissions.py 加 `hasattr(outbound_queue, "send")` 動態判斷,兩種都吃。

### 3. `_get_secret` 用 module-level `_runtime_secret` 而非 function attribute

`func._cached = ...` 是合法 Python,但 mypy strict 看不出 `func._cached` 的型別,
警告 "Returning Any"。**改用 `global _runtime_secret`**,mypy 滿意。

### 4. WebSocket auth 透過 query string

`OAuth2PasswordBearer` / `HTTPBearer` 都不支援 WS。chat.py 用 `Annotated[str, Query(...)]`
從 `?token=...` 取 JWT,handler 內手動 `verify_token`,失敗 ws.close(1008)。
spec 踩雷有提。

### 5. 三 task fan-in 用 anyio.create_memory_object_stream

writer / reader / runner 三 coroutine 共享 ws,不能多處直接 ws.send_json。
**writer 是唯一寫端;outbound_send 是 single-producer-multi-consumer(實際 SPSC)**。
runner / can_use_tool callback 都把 event 推進 outbound_send。

### 6. WebSocket lifecycle:reader 結束 → writer 結束 → ws close

reader try/finally 內推 _QUEUE_SENTINEL → writer 收到 sentinel return → task group 退。
最後 finally 呼 ws.close()。WebSocketDisconnect 直接 catch 不 propagate,確保 task group cleanup 不被 unhandled exception 阻擋。

### 7. lifespan 沒跑時 deps 自動建

TestClient 直接用 `client = TestClient(create_app())` 不一定會跑 lifespan(視 starlette 版本)。
deps.py 內若 `app.state.session_manager` 不存在 → 自動建一個。讓 unit test 不需 with TestClient context。

### 8. Conversation system_prompt 在 Phase 6 場景變空字串

Conversation.system_prompt 預設 `""`(Phase 4 後 assembler 走動態組裝)。
ws chat 直接呼 `Conversation(provider=..., user_id=..., session_id=...)`,沒傳 system_prompt
→ 走 assembler,自動含 7 段靜態 + memory + env。**Phase 6 不重複組 prompt 邏輯**。

---

## Phase 6 鋪好的基礎

| 後續 phase 將用到 | 使用情況 |
|---|---|
| Phase 7(production)| `SessionManager` interface 換 Postgres 實作;`/auth/login` 換真 OAuth;Redis pub/sub 跨 instance event |
| Phase 7(sandbox)| Conversation 起時注入 sandbox-aware Bash / Edit tools |
| Phase 8(hooks / plugins)| pre/post hook 透過 ws 派發進階 event |
| Phase 11+(MCP web OAuth)| `/mcp/oauth/start` + `/mcp/oauth/callback` endpoints,接 secureStorage |

## 衍生的新 phase plan

無 — Phase 6 觀察到的全部進範圍。
